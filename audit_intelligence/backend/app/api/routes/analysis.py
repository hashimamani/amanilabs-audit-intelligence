from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import RunAnalysisIn, RunOut
from app.core.auth import Principal, get_current_tenant, get_current_user
from app.core.datasets import DEFAULT_DATASET_ID
from app.db import repository as repo
from app.db.repository import Tenant
from app.jobs import service as jobs

router = APIRouter(prefix="/analysis", tags=["analysis"])


def to_run_out(run: dict) -> RunOut:
    return RunOut(id=run["run_id"], **{k: run.get(k) for k in RunOut.model_fields if k != "id"})


@router.post("/run", response_model=RunOut, status_code=202)
def run_analysis(
    payload: RunAnalysisIn,
    tenant: Tenant = Depends(get_current_tenant),
    user: Principal = Depends(get_current_user),
):
    dataset_id = payload.dataset_id or DEFAULT_DATASET_ID
    if dataset_id != DEFAULT_DATASET_ID:
        dataset = repo.get_dataset(tenant.slug, dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail=f"No uploaded dataset found for id '{dataset_id}'")
        if dataset.get("status") != "ready":
            raise HTTPException(status_code=400, detail=f"Dataset '{dataset_id}' is {dataset.get('status')}, not ready")

    run = repo.create_run(tenant.slug, dataset_id)
    job = repo.create_job(tenant.slug, kind="analysis", payload={"run_id": run["run_id"], "dataset_id": dataset_id}, created_by=user.email)
    repo.update_run(tenant.slug, run["run_id"], job_id=job["job_id"])
    jobs.dispatch(tenant.slug, job["job_id"])
    return to_run_out(repo.get_run(tenant.slug, run["run_id"]))


@router.get("/runs", response_model=list[RunOut])
def list_runs(tenant: Tenant = Depends(get_current_tenant)):
    return [to_run_out(r) for r in repo.list_runs(tenant.slug)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, tenant: Tenant = Depends(get_current_tenant)):
    run = repo.get_run(tenant.slug, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return to_run_out(run)
