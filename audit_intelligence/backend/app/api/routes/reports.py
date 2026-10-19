from fastapi import APIRouter, Depends, HTTPException

from app.api.schemas import JobOut, ReportGenerateIn
from app.core.ai import get_anthropic_client
from app.core.auth import Principal, get_current_user
from app.core.budget import enforce_ai_budget
from app.db.repository import Tenant
from app.jobs import service as jobs
from app.jobs.report import MAX_REPORT_CASES

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=JobOut, status_code=202)
def generate_report(
    payload: ReportGenerateIn,
    tenant: Tenant = Depends(enforce_ai_budget),
    user: Principal = Depends(get_current_user),
    _client=Depends(get_anthropic_client),
):
    if payload.case_ids and len(payload.case_ids) > MAX_REPORT_CASES:
        raise HTTPException(status_code=400, detail=f"Select at most {MAX_REPORT_CASES} cases for a single report.")
    job = jobs.submit(tenant.slug, user, kind="report", payload={"case_ids": payload.case_ids})
    return jobs.public_job(job)
