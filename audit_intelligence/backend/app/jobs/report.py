"""
AI-drafted board/leadership report over a batch of real cases. Same
grounding discipline as case Q&A (routes/cases.py), just wider: Claude
only ever narrates the real evidence records handed to it, cited per
case, and is explicitly forbidden from rendering a fraud verdict - that
judgment stays with the audit team and board. Runs as a background job:
Opus over up to 20 cases takes close to a minute.
"""

from app.core.ai import call_claude, case_to_grounding_text, get_anthropic_client
from app.db import repository as repo

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


def select_cases_for_report(tenant_slug: str, case_refs: list[str] | None) -> list[dict]:
    if case_refs:
        return repo.get_cases(tenant_slug, case_refs)
    run = repo.latest_run(tenant_slug)
    if run is None:
        return []
    summaries = repo.list_case_summaries(tenant_slug, run["run_id"], severities=["Critical", "High"])
    return repo.get_cases(tenant_slug, [s["case_ref"] for s in summaries[:DEFAULT_REPORT_CASE_LIMIT]])


def run_report(tenant_slug: str, case_refs: list[str] | None, client) -> dict:
    cases = select_cases_for_report(tenant_slug, case_refs)
    generated_at = repo.utcnow_iso()
    if not cases:
        return {"report_text": "No cases matched this report's criteria.", "case_count": 0, "generated_at": generated_at}

    batch = "\n\n".join(f"=== Case: {c['case_ref']} ===\n\n{case_to_grounding_text(c)}" for c in cases)
    response = call_claude(
        client,
        max_tokens=8192,
        system=REPORT_SYSTEM_PROMPT.format(grounding_context=batch),
        messages=[{"role": "user", "content": "Draft the report."}],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if response.stop_reason == "max_tokens":
        text += "\n\n[Report was truncated — try selecting fewer cases.]"
    if not text:
        text = "The AI didn't return a report. Please try again."
    return {"report_text": text, "case_count": len(cases), "generated_at": generated_at}


def run_report_job(tenant_slug: str, job: dict) -> dict:
    return run_report(tenant_slug, job["payload"].get("case_ids"), get_anthropic_client())
