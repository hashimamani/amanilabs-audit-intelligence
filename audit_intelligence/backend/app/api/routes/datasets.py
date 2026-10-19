from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.schemas import DatasetCreateOut, DatasetOut
from app.core import datasets
from app.core.auth import get_current_tenant
from app.core.settings import get_settings
from app.db import repository as repo
from app.db.repository import Tenant

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("", response_model=DatasetCreateOut, status_code=201)
def create_dataset(tenant: Tenant = Depends(get_current_tenant)):
    dataset, targets = datasets.create_dataset(tenant.slug)
    uploads = [{"file": t.file, "url": _with_tenant(t.url, tenant.slug), "method": t.method} for t in targets]
    return DatasetCreateOut(dataset_id=dataset["dataset_id"], uploads=uploads)


def _with_tenant(url: str, slug: str) -> str:
    return f"{url}&tenant={slug}" if url.startswith("/datasets/") else url


@router.put("/{dataset_id}/files/{name}", status_code=204)
async def put_local_file(
    dataset_id: str,
    name: str,
    request: Request,
    tenant: str = Query(...),
    expires: int = Query(...),
    token: str = Query(...),
):
    """Local-mode stand-in for a presigned S3 PUT. The token, not a login,
    authorises the write - exactly like the presigned URL it replaces."""
    if get_settings().dataset_store != "local":
        raise HTTPException(status_code=404, detail="Not found")
    if name not in datasets.REQUIRED_FILES or not datasets.verify_local_upload_token(tenant, dataset_id, name, expires, token):
        raise HTTPException(status_code=403, detail="Upload URL is invalid or expired")
    if repo.get_dataset(tenant, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    datasets.store_local_file(tenant, dataset_id, name, await request.body())


@router.post("/{dataset_id}/finalize", response_model=DatasetOut)
def finalize_dataset(dataset_id: str, tenant: Tenant = Depends(get_current_tenant)):
    try:
        return datasets.finalize_dataset(tenant.slug, dataset_id)
    except datasets.DatasetNotFoundError:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")


@router.get("", response_model=list[DatasetOut])
def list_datasets(tenant: Tenant = Depends(get_current_tenant)):
    return repo.list_datasets(tenant.slug)
