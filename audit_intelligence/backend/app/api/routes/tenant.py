from fastapi import APIRouter, Depends

from app.core.tenancy import get_current_tenant
from app.db.models import TenantORM
from app.api.schemas import TenantOut

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("/me", response_model=TenantOut)
def get_current_tenant_info(tenant: TenantORM = Depends(get_current_tenant)):
    return tenant
