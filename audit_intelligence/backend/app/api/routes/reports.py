"""
AI-drafted board/leadership report over a batch of real cases. Same
grounding discipline as case Q&A (routes/cases.py), just wider: Claude
only ever narrates the real evidence records handed to it, cited per
case, and is explicitly forbidden from rendering a fraud verdict - that
judgment stays with the audit team and board. No new persistence -
ephemeral like case Q&A, generated fresh on each request.
"""

from datetime import datetime, timezone

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import ReportGenerateIn, ReportGenerateOut
from app.core.ai import call_claude, case_to_grounding_text, get_anthropic_client
from app.core.auth import get_current_tenant
from app.core.db import get_db
from app.db.models import AnalysisRunORM, CaseORM, TenantORM

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_REPORT_CASES = 50
DEFAULT_REPORT_CASE_LIMIT = 20

REPORT_SYSTEM_PROMPT = """You are drafting a fraud-audit report for a SACCO's board or leadership review, based on real case records from an internal fraud-detection system. Below are the complete evidence records for the cases included in this report, taken verbatim from the case-management database.

Rules — follow these exactly:
1. Base every statement ONLY on the CASE RECORDS below. Never state a fact, number, date, or name that is not verbatim in the records, or a direct arithmetic computation over numbers that are both verbatim in the records (e.g. totals, counts).
2. For each case, mention which flag or evidence item supports each claim so a reader can trace it back.
3. Do not render a verdict on whether fraud occurred in any case — describe what the evidence shows and flag it for investigation. That judgment belongs to the audit team and board.
4. Write for a non-technical board audience: plain language, no jargon, no rule IDs without a one-line explanation of what they mean.
5. Structure the report as: (a) a short executive summary, (b) one section per case, (c) a closing "Recommended next steps" section synthesizing the suggested steps already present in the case records — do not invent new recommendations.
6. Format as plain text: blank lines between sections, section titles in Title Case on their own line. Do not use markdown syntax (no #, no **, no bullet dashes for headings).
7. Keep the tone factual and measured — this is an internal audit report, not a marketing document.

CASE RECORDS:
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


def _select_cases_for_report(db: Session, tenant_id: int, case_ids: list[int] | None) -> list[CaseORM]:
    if case_ids:
        return (
            db.query(CaseORM)
            .filter(CaseORM.id.in_(case_ids), CaseORM.tenant_id == tenant_id)
            .order_by(CaseORM.risk_score.desc())
            .all()
        )

    run_id = _latest_run_id(db, tenant_id)
    if run_id is None:
        return []
    return (
        db.query(CaseORM)
        .filter(
            CaseORM.tenant_id == tenant_id,
            CaseORM.run_id == run_id,
            CaseORM.severity.in_(["Critical", "High"]),
        )
        .order_by(CaseORM.risk_score.desc())
        .limit(DEFAULT_REPORT_CASE_LIMIT)
        .all()
    )


@router.post("/generate", response_model=ReportGenerateOut)
def generate_report(
    payload: ReportGenerateIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    if payload.case_ids and len(payload.case_ids) > MAX_REPORT_CASES:
        raise HTTPException(
            status_code=400,
            detail=f"Select at most {MAX_REPORT_CASES} cases for a single report.",
        )

    cases = _select_cases_for_report(db, tenant.id, payload.case_ids)
    if not cases:
        return ReportGenerateOut(
            report_text="No cases matched this report's criteria.",
            case_count=0,
            generated_at=datetime.now(timezone.utc),
        )

    batch = "\n\n".join(
        f"=== Case: {c.case_ref} ===\n\n{case_to_grounding_text(c)}" for c in cases
    )
    response = call_claude(
        client,
        max_tokens=4096,
        system=REPORT_SYSTEM_PROMPT.format(grounding_context=batch),
        messages=[{"role": "user", "content": "Draft the report."}],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if response.stop_reason == "max_tokens":
        text += "\n\n[Report was truncated — try selecting fewer cases.]"
    if not text:
        text = "The AI didn't return a report. Please try again."

    return ReportGenerateOut(report_text=text, case_count=len(cases), generated_at=datetime.now(timezone.utc))
