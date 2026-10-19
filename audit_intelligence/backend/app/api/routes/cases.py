import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import (
    ActivityOut,
    BulkCaseStatusIn,
    BulkCaseStatusOut,
    CaseAskIn,
    CaseAskOut,
    CaseDetailOut,
    CaseSummaryOut,
    CaseUpdateIn,
)
from app.core.ai import call_claude, case_to_grounding_text, get_anthropic_client
from app.core.auth import Principal, get_current_tenant, get_current_user
from app.db import repository as repo
from app.db.repository import Tenant

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


def to_summary(row: dict) -> CaseSummaryOut:
    return CaseSummaryOut(id=row["case_ref"], **{k: row.get(k) for k in CaseSummaryOut.model_fields if k != "id"})


def to_detail(row: dict) -> CaseDetailOut:
    return CaseDetailOut(id=row["case_ref"], **{k: row.get(k) for k in CaseDetailOut.model_fields if k != "id"})


def _get_or_404(tenant: Tenant, case_ref: str) -> dict:
    row = repo.get_case(tenant.slug, case_ref)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_ref} not found")
    return row


@router.get("", response_model=list[CaseSummaryOut])
def list_cases(
    run_id: int | None = Query(None, description="Defaults to the most recent completed analysis run"),
    status: str | None = None,
    severity: str | None = None,
    min_risk: float | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    tenant: Tenant = Depends(get_current_tenant),
):
    if run_id is None:
        latest = repo.latest_run(tenant.slug)
        if latest is None:
            return []
        run_id = latest["run_id"]
    rows = repo.list_case_summaries(tenant.slug, run_id, status=status, severity=severity, min_risk=min_risk)
    return [to_summary(r) for r in rows[offset:offset + limit]]


@router.patch("/bulk-status", response_model=BulkCaseStatusOut)
def bulk_update_status(
    payload: BulkCaseStatusIn,
    tenant: Tenant = Depends(get_current_tenant),
    user: Principal = Depends(get_current_user),
):
    updated = 0
    for case_ref in payload.case_ids:
        before = repo.get_case(tenant.slug, case_ref)
        if before is None:
            continue
        repo.update_case(tenant.slug, case_ref, status=payload.status)
        updated += 1
        if before["status"] != payload.status:
            repo.add_activity(
                tenant.slug, case_ref, actor_email=user.email, actor_name=user.name,
                action="status_changed", detail={"from": before["status"], "to": payload.status, "bulk": True},
            )
    return BulkCaseStatusOut(updated_count=updated)


@router.get("/{case_ref}", response_model=CaseDetailOut)
def get_case(case_ref: str, tenant: Tenant = Depends(get_current_tenant)):
    return to_detail(_get_or_404(tenant, case_ref))


@router.get("/{case_ref}/activity", response_model=list[ActivityOut])
def get_case_activity(case_ref: str, tenant: Tenant = Depends(get_current_tenant)):
    _get_or_404(tenant, case_ref)
    return repo.list_activity(tenant.slug, case_ref)


@router.patch("/{case_ref}", response_model=CaseDetailOut)
def update_case(
    case_ref: str,
    payload: CaseUpdateIn,
    tenant: Tenant = Depends(get_current_tenant),
    user: Principal = Depends(get_current_user),
):
    before = _get_or_404(tenant, case_ref)
    after = repo.update_case(
        tenant.slug, case_ref, status=payload.status, assigned_auditor=payload.assigned_auditor,
        outcome=payload.outcome, add_note=payload.add_note,
    )

    def record(action: str, detail: dict) -> None:
        repo.add_activity(tenant.slug, case_ref, actor_email=user.email, actor_name=user.name, action=action, detail=detail)

    if payload.status is not None and payload.status != before["status"]:
        record("status_changed", {"from": before["status"], "to": payload.status})
    if payload.assigned_auditor is not None and payload.assigned_auditor != (before.get("assigned_auditor") or ""):
        record("assigned", {"from": before.get("assigned_auditor"), "to": payload.assigned_auditor})
    if payload.outcome is not None and payload.outcome != (before.get("outcome") or ""):
        record("outcome_set", {"from": before.get("outcome"), "to": payload.outcome})
    if payload.add_note is not None:
        record("note_added", {"note": payload.add_note})
    return to_detail(after)


@router.post("/{case_ref}/ask", response_model=CaseAskOut)
def ask_case_question(
    case_ref: str,
    payload: CaseAskIn,
    tenant: Tenant = Depends(get_current_tenant),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    row = _get_or_404(tenant, case_ref)
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
