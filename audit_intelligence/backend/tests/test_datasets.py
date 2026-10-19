"""
Uploading a dataset: the API hands out one URL per file, the client PUTs
the files, finalize validates the headers. Local mode goes through the
API's own file route; S3 mode through presigned URLs on a moto bucket.
"""

from pathlib import Path

import boto3
import pytest

from app.core import datasets
from app.core.settings import get_settings
from conftest import DATA_DIR


def _upload_all(client, token, headers, files: dict[str, bytes]):
    created = client.post("/datasets", headers=headers(token))
    assert created.status_code == 201, created.text
    body = created.json()
    for target in body["uploads"]:
        resp = client.put(target["url"], content=files[target["file"]], headers={"Content-Type": "text/csv"})
        assert resp.status_code == 204, (target["file"], resp.text)
    return body["dataset_id"]


def _demo_files() -> dict[str, bytes]:
    return {name: (DATA_DIR / name).read_bytes() for name in datasets.REQUIRED_FILES}


def test_local_upload_finalize_and_analyse(client, default_token, headers, run_demo_analysis):
    dataset_id = _upload_all(client, default_token, headers, _demo_files())
    finalized = client.post(f"/datasets/{dataset_id}/finalize", headers=headers(default_token)).json()
    assert finalized == {**finalized, "status": "ready", "errors": []}

    baseline = run_demo_analysis()
    resp = client.post("/analysis/run", json={"dataset_id": dataset_id}, headers=headers(default_token))
    assert resp.status_code == 202
    run = resp.json()
    assert run["status"] == "succeeded", run
    assert (run["flag_count"], run["case_count"]) == (baseline["flag_count"], baseline["case_count"])
    assert run["dataset_id"] == dataset_id
    assert any(d["dataset_id"] == dataset_id for d in client.get("/datasets", headers=headers(default_token)).json())


def test_missing_columns_make_the_dataset_invalid(client, default_token, headers):
    files = _demo_files()
    files["members.csv"] = b"member_id,name\nM1,Someone\n"
    dataset_id = _upload_all(client, default_token, headers, files)
    finalized = client.post(f"/datasets/{dataset_id}/finalize", headers=headers(default_token)).json()
    assert finalized["status"] == "invalid"
    assert finalized["errors"] == ["members.csv: missing column(s) national_id, phone, branch_id, join_date"]

    resp = client.post("/analysis/run", json={"dataset_id": dataset_id}, headers=headers(default_token))
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"]


def test_unfinalized_or_unknown_dataset_cannot_be_analysed(client, default_token, headers):
    created = client.post("/datasets", headers=headers(default_token)).json()
    assert client.post("/analysis/run", json={"dataset_id": created["dataset_id"]}, headers=headers(default_token)).status_code == 400
    assert client.post("/analysis/run", json={"dataset_id": "nope"}, headers=headers(default_token)).status_code == 404
    finalized = client.post(f"/datasets/{created['dataset_id']}/finalize", headers=headers(default_token)).json()
    assert finalized["status"] == "invalid"
    assert all(e.endswith("file not uploaded") for e in finalized["errors"])


def test_upload_url_token_is_required_and_scoped(client, default_token, headers):
    created = client.post("/datasets", headers=headers(default_token)).json()
    target = created["uploads"][0]
    tampered = target["url"].replace("token=", "token=0")
    assert client.put(tampered, content=b"x").status_code == 403
    other_file = target["url"].replace(target["file"], "branches.csv")
    assert client.put(other_file, content=b"x").status_code == 403
    assert client.put(target["url"].replace("tenant=default", "tenant=other"), content=b"x").status_code == 403


def test_another_tenant_cannot_finalize_or_run_my_dataset(client, default_token, headers, provision_tenant):
    other_token = provision_tenant("datasets-other", "Other Tenant")
    dataset_id = _upload_all(client, default_token, headers, _demo_files())
    assert client.post(f"/datasets/{dataset_id}/finalize", headers=headers(other_token)).status_code == 404
    assert client.post("/analysis/run", json={"dataset_id": dataset_id}, headers=headers(other_token)).status_code == 404


@pytest.fixture
def s3_mode(monkeypatch):
    boto3.client("s3", region_name="eu-west-1").create_bucket(
        Bucket="audit-intelligence-test-datasets", CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
    )
    monkeypatch.setenv("DATASET_STORE", "s3")
    monkeypatch.setenv("DATASETS_BUCKET", "audit-intelligence-test-datasets")
    get_settings.cache_clear()
    datasets.reset_clients()
    yield
    get_settings.cache_clear()
    datasets.reset_clients()


def test_s3_mode_presigns_validates_and_materializes(s3_mode):
    dataset, targets = datasets.create_dataset("default")
    assert len(targets) == 8
    assert all(t.url.startswith("https://") and "audit-intelligence-test-datasets" in t.url for t in targets)

    s3 = boto3.client("s3", region_name="eu-west-1")
    for name in datasets.REQUIRED_FILES:
        s3.put_object(Bucket="audit-intelligence-test-datasets", Key=f"tenants/default/datasets/{dataset['dataset_id']}/{name}", Body=(DATA_DIR / name).read_bytes())

    finalized = datasets.finalize_dataset("default", dataset["dataset_id"])
    assert finalized["status"] == "ready"

    path = datasets.materialize("default", dataset["dataset_id"])
    assert sorted(p.name for p in Path(path).iterdir()) == sorted(datasets.REQUIRED_FILES)
    datasets.discard_materialized(path)
    assert not path.exists()
    assert datasets.materialize("default", None) == get_settings().demo_dataset_dir
