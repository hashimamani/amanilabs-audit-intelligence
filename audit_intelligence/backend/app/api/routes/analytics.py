from fastapi import APIRouter, Depends

from app.api.schemas import AnalyticsQueryIn, JobOut
from app.core.ai import get_anthropic_client
from app.core.auth import Principal, get_current_tenant, get_current_user
from app.db.repository import Tenant
from app.jobs import service as jobs

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/query", response_model=JobOut, status_code=202)
def analytics_query(
    payload: AnalyticsQueryIn,
    tenant: Tenant = Depends(get_current_tenant),
    user: Principal = Depends(get_current_user),
    _client=Depends(get_anthropic_client),
):
    job = jobs.submit(tenant.slug, user, kind="analytics", payload={"question": payload.question})
    return jobs.public_job(job)
