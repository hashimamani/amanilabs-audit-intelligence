from fastapi import APIRouter, Depends

from app.api.schemas import RuleOut
from app.core.auth import get_current_user
from app.rules.catalogue import rule_catalogue

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("", response_model=list[RuleOut])
def list_rules(_user=Depends(get_current_user)):
    return rule_catalogue()
