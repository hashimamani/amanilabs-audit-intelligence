from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.db.models import CaseORM, AnalysisRunORM
from app.api.schemas import CaseSummaryOut, CaseDetailOut, CaseUpdateIn

router = APIRouter(prefix="/cases", tags=["cases"])


def _latest_run_id(db: Session) -> int | None:
    latest = db.query(AnalysisRunORM).order_by(AnalysisRunORM.created_at.desc()).first()
    return latest.id if latest else None


def _to_summary(row: CaseORM) -> CaseSummaryOut:
    return CaseSummaryOut(
        id=row.id,
        case_ref=row.case_ref,
        run_id=row.run_id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_name=row.subject_name,
        risk_score=row.risk_score,
        severity=row.severity,
        status=row.status,
        triggered_rules=row.triggered_rules,
        flag_count=len(row.flags),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[CaseSummaryOut])
def list_cases(
    run_id: int | None = Query(None, description="Defaults to the most recent analysis run"),
    status: str | None = None,
    severity: str | None = None,
    min_risk: float | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    effective_run_id = run_id if run_id is not None else _latest_run_id(db)
    if effective_run_id is None:
        return []

    q = db.query(CaseORM).filter(CaseORM.run_id == effective_run_id)
    if status:
        q = q.filter(CaseORM.status == status)
    if severity:
        q = q.filter(CaseORM.severity == severity)
    if min_risk is not None:
        q = q.filter(CaseORM.risk_score >= min_risk)

    rows = q.order_by(CaseORM.risk_score.desc()).offset(offset).limit(limit).all()
    return [_to_summary(r) for r in rows]


@router.get("/{case_id}", response_model=CaseDetailOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    row = db.get(CaseORM, case_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return row


@router.patch("/{case_id}", response_model=CaseDetailOut)
def update_case(case_id: int, payload: CaseUpdateIn, db: Session = Depends(get_db)):
    row = db.get(CaseORM, case_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    if payload.status is not None:
        row.status = payload.status
    if payload.assigned_auditor is not None:
        row.assigned_auditor = payload.assigned_auditor
    if payload.outcome is not None:
        row.outcome = payload.outcome
    if payload.add_note is not None:
        row.notes = [*row.notes, payload.add_note]

    db.commit()
    db.refresh(row)
    return row
