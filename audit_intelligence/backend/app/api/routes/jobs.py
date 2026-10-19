from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import JobOut
from app.core.auth import get_current_tenant
from app.db import repository as repo
from app.db.repository import Tenant
from app.jobs.service import public_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, tenant: Tenant = Depends(get_current_tenant)):
    job = repo.get_job(tenant.slug, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return public_job(job)
