from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.datasets import resolve_dataset_dir, DatasetNotFoundError, DEFAULT_DATASET_ID
from app.core.tenancy import get_current_tenant
from app.db.models import AnalysisRunORM, TenantORM
from app.rules.dataset import SaccoDataset
from app.rules.engine import RuleEngine
from app.cases.builder import build_cases
from app.cases.persistence import save_cases
from app.api.schemas import RunAnalysisIn, RunSummaryOut

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run", response_model=RunSummaryOut)
def run_analysis(
    payload: RunAnalysisIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
):
    dataset_id = payload.dataset_id or DEFAULT_DATASET_ID
    try:
        dataset_dir = resolve_dataset_dir(payload.dataset_id, tenant.slug)
    except DatasetNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    dataset = SaccoDataset(str(dataset_dir))
    flags = RuleEngine().run(dataset)
    cases = build_cases(flags, dataset=dataset)

    run = AnalysisRunORM(
        tenant_id=tenant.id,
        dataset_id=dataset_id,
        dataset_dir=str(dataset_dir),
        flag_count=len(flags),
        case_count=len(cases),
    )
    db.add(run)
    db.flush()  # assigns run.id, needed for case_ref generation

    save_cases(db, run, cases)
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs", response_model=list[RunSummaryOut])
def list_runs(db: Session = Depends(get_db), tenant: TenantORM = Depends(get_current_tenant)):
    return (
        db.query(AnalysisRunORM)
        .filter(AnalysisRunORM.tenant_id == tenant.id)
        .order_by(AnalysisRunORM.created_at.desc())
        .all()
    )
