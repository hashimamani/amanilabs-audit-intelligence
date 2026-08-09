import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.auth import get_current_tenant
from app.core.ai import call_claude, case_to_grounding_text, get_anthropic_client
from app.db.models import CaseORM, AnalysisRunORM, TenantORM
from app.api.schemas import (
    CaseSummaryOut,
    CaseDetailOut,
    CaseUpdateIn,
    BulkCaseStatusIn,
    BulkCaseStatusOut,
    CaseAskIn,
    CaseAskOut,
)

router = APIRouter(prefix="/cases", tags=["cases"])

CASE_QA_SYSTEM_PROMPT = """You are an assistant embedded in an internal fraud-audit tool. An auditor is asking a question about ONE specific case. Below is that case's complete evidence record, taken verbatim from the case-management database.

Rules — follow these exactly:
1. Answer using ONLY the information in the CASE RECORD below. Do not use outside knowledge, do not guess, and do not infer facts that are not explicitly present in the record.
2. If the question cannot be answered from the case record, say so plainly (e.g. "The case record doesn't include that information") instead of speculating.
3. Never state a number, date, name, or other fact that is not verbatim in the CASE RECORD, or a direct arithmetic computation over numbers that are both verbatim in the record.
4. When you state a fact, say which flag, evidence item, or note it came from so the auditor can verify it.
5. Do not offer an investigative conclusion or a verdict on whether fraud occurred — only explain what the evidence shows. That judgment belongs to the auditor.
6. Keep answers concise.

CASE RECORD:
{grounding_context}
"""


def _latest_run_id(db: Session, tenant_id: int) -> int | None:
    latest = (
        db.query(AnalysisRunORM)
        .filter(AnalysisRunORM.tenant_id == tenant_id)
        .order_by(AnalysisRunORM.created_at.desc())
        .first()
    )
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
    tenant: TenantORM = Depends(get_current_tenant),
):
    effective_run_id = run_id if run_id is not None else _latest_run_id(db, tenant.id)
    if effective_run_id is None:
        return []

    q = db.query(CaseORM).filter(
        CaseORM.run_id == effective_run_id,
        CaseORM.tenant_id == tenant.id,
    )
    if status:
        q = q.filter(CaseORM.status == status)
    if severity:
        q = q.filter(CaseORM.severity == severity)
    if min_risk is not None:
        q = q.filter(CaseORM.risk_score >= min_risk)

    rows = q.order_by(CaseORM.risk_score.desc()).offset(offset).limit(limit).all()
    return [_to_summary(r) for r in rows]


@router.patch("/bulk-status", response_model=BulkCaseStatusOut)
def bulk_update_status(
    payload: BulkCaseStatusIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
):
    if not payload.case_ids:
        return BulkCaseStatusOut(updated_count=0)

    updated = (
        db.query(CaseORM)
        .filter(CaseORM.id.in_(payload.case_ids), CaseORM.tenant_id == tenant.id)
        .update({"status": payload.status}, synchronize_session=False)
    )
    db.commit()
    return BulkCaseStatusOut(updated_count=updated)


@router.get("/{case_id}", response_model=CaseDetailOut)
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
):
    row = db.query(CaseORM).filter(CaseORM.id == case_id, CaseORM.tenant_id == tenant.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return row


@router.patch("/{case_id}", response_model=CaseDetailOut)
def update_case(
    case_id: int,
    payload: CaseUpdateIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
):
    row = db.query(CaseORM).filter(CaseORM.id == case_id, CaseORM.tenant_id == tenant.id).first()
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


@router.post("/{case_id}/ask", response_model=CaseAskOut)
def ask_case_question(
    case_id: int,
    payload: CaseAskIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    row = db.query(CaseORM).filter(CaseORM.id == case_id, CaseORM.tenant_id == tenant.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    system_prompt = CASE_QA_SYSTEM_PROMPT.format(grounding_context=case_to_grounding_text(row))
    response = call_claude(
        client,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": payload.question}],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if response.stop_reason == "max_tokens":
        text += "\n\n[Response was truncated — ask a more specific question.]"
    if not text:
        text = "The AI didn't return an answer for this question. Please try rephrasing."
    return CaseAskOut(answer=text)
