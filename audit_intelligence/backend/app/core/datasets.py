"""
Where a tenant's uploaded CSVs live, and the contract for getting them there.

Uploads never pass through the API: the API hands out one URL per required
file, the browser PUTs each file straight to it, then calls finalize, which
reads each file's header and refuses the dataset if a column the rules need
is missing - before any analysis is queued, not inside the worker.

S3 mode: the URLs are presigned PUTs on the datasets bucket.
Local mode: the URLs point back at this API (PUT /datasets/{id}/files/{name})
carrying an HMAC token, so the browser code is the same in both modes.
"""

import hashlib
import hmac
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

from app.core.settings import get_settings
from app.db import repository as repo

DEFAULT_DATASET_ID = "default"

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "members.csv": ["member_id", "name", "national_id", "phone", "branch_id", "join_date"],
    "branches.csv": ["branch_id", "branch_name"],
    "employees.csv": ["employee_id", "name", "role", "branch_id"],
    "accounts.csv": ["account_id", "member_id", "account_type"],
    "transactions.csv": ["transaction_id", "account_id", "member_id", "transaction_type", "amount", "timestamp", "recipient"],
    "loans.csv": ["loan_id", "member_id", "amount", "approved_by", "approval_timestamp", "disbursement_timestamp", "status"],
    "guarantors.csv": ["loan_id", "guarantor_member_id"],
    "loan_payments.csv": ["payment_id", "loan_id", "amount", "payment_timestamp"],
}
REQUIRED_FILES = list(REQUIRED_COLUMNS)

HEADER_BYTES = 65536


class DatasetNotFoundError(Exception):
    pass


class DatasetNotReadyError(Exception):
    pass


@dataclass(frozen=True)
class UploadTarget:
    file: str
    url: str
    method: str = "PUT"


@lru_cache(maxsize=1)
def s3_client():
    settings = get_settings()
    return boto3.client("s3", region_name=settings.aws_region, config=Config(signature_version="s3v4"))


def reset_clients() -> None:
    s3_client.cache_clear()


def _s3_key(tenant_slug: str, dataset_id: str, name: str) -> str:
    return f"tenants/{tenant_slug}/datasets/{dataset_id}/{name}"


def _local_dir(tenant_slug: str, dataset_id: str) -> Path:
    return get_settings().uploads_dir / tenant_slug / dataset_id


# --- local upload tokens ---------------------------------------------------

def _local_token(tenant_slug: str, dataset_id: str, name: str, expires: int) -> str:
    message = f"{tenant_slug}:{dataset_id}:{name}:{expires}".encode()
    return hmac.new(get_settings().local_jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def verify_local_upload_token(tenant_slug: str, dataset_id: str, name: str, expires: int, token: str) -> bool:
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(_local_token(tenant_slug, dataset_id, name, expires), token)


# --- lifecycle -------------------------------------------------------------

def create_dataset(tenant_slug: str) -> tuple[dict, list[UploadTarget]]:
    settings = get_settings()
    dataset_id = uuid.uuid4().hex[:12]
    expires = int(time.time()) + settings.upload_url_ttl_seconds
    targets = []
    for name in REQUIRED_FILES:
        if settings.dataset_store == "s3":
            url = s3_client().generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.datasets_bucket, "Key": _s3_key(tenant_slug, dataset_id, name), "ContentType": "text/csv"},
                ExpiresIn=settings.upload_url_ttl_seconds,
            )
        else:
            token = _local_token(tenant_slug, dataset_id, name, expires)
            url = f"/datasets/{dataset_id}/files/{name}?expires={expires}&token={token}"
        targets.append(UploadTarget(file=name, url=url))
    dataset = repo.put_dataset(tenant_slug, {
        "dataset_id": dataset_id, "status": "pending", "files": REQUIRED_FILES,
        "created_at": repo.utcnow_iso(), "errors": [],
    })
    return dataset, targets


def store_local_file(tenant_slug: str, dataset_id: str, name: str, content: bytes) -> None:
    directory = _local_dir(tenant_slug, dataset_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(content)


def _read_header(tenant_slug: str, dataset_id: str, name: str) -> str | None:
    settings = get_settings()
    if settings.dataset_store == "s3":
        try:
            body = s3_client().get_object(
                Bucket=settings.datasets_bucket, Key=_s3_key(tenant_slug, dataset_id, name), Range=f"bytes=0-{HEADER_BYTES - 1}",
            )["Body"].read()
        except s3_client().exceptions.NoSuchKey:
            return None
    else:
        path = _local_dir(tenant_slug, dataset_id) / name
        if not path.is_file():
            return None
        with path.open("rb") as f:
            body = f.read(HEADER_BYTES)
    first_line = body.split(b"\n", 1)[0]
    return first_line.decode("utf-8-sig", errors="replace").strip()


def validate_headers(tenant_slug: str, dataset_id: str) -> list[str]:
    errors = []
    for name, required in REQUIRED_COLUMNS.items():
        header = _read_header(tenant_slug, dataset_id, name)
        if header is None:
            errors.append(f"{name}: file not uploaded")
            continue
        columns = {c.strip().strip('"') for c in header.split(",")}
        missing = [c for c in required if c not in columns]
        if missing:
            errors.append(f"{name}: missing column(s) {', '.join(missing)}")
    return errors


def finalize_dataset(tenant_slug: str, dataset_id: str) -> dict:
    dataset = repo.get_dataset(tenant_slug, dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(dataset_id)
    errors = validate_headers(tenant_slug, dataset_id)
    dataset = {**dataset, "status": "ready" if not errors else "invalid", "errors": errors, "finalized_at": repo.utcnow_iso()}
    return repo.put_dataset(tenant_slug, dataset)


def materialize(tenant_slug: str, dataset_id: str | None) -> Path:
    """A directory on local disk holding the dataset's CSVs, ready for
    SaccoDataset. S3 datasets are downloaded to a temp directory."""
    settings = get_settings()
    if dataset_id is None or dataset_id == DEFAULT_DATASET_ID:
        return settings.demo_dataset_dir
    dataset = repo.get_dataset(tenant_slug, dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(f"No uploaded dataset found for id '{dataset_id}'")
    if dataset.get("status") != "ready":
        raise DatasetNotReadyError(f"Dataset '{dataset_id}' is {dataset.get('status')}, not ready")
    if settings.dataset_store != "s3":
        return _local_dir(tenant_slug, dataset_id)
    target = Path(tempfile.mkdtemp(prefix=f"dataset-{dataset_id}-"))
    for name in REQUIRED_FILES:
        s3_client().download_file(settings.datasets_bucket, _s3_key(tenant_slug, dataset_id, name), str(target / name))
    return target


def discard_materialized(path: Path) -> None:
    settings = get_settings()
    if settings.dataset_store == "s3" and path != settings.demo_dataset_dir and path.name.startswith("dataset-"):
        shutil.rmtree(path, ignore_errors=True)
