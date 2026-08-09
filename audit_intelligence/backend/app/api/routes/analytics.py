"""
"Ask for a chart" analytics, backed by Claude's code execution tool.
Claude never STATES a number - it writes and runs real Python/pandas
code against the tenant's real (privacy-minimized) case data, and the
code's own printed output is the chart. A number produced by code that
actually ran against real rows isn't invented, it's computed - same
"never invent evidence" guarantee the rest of this app relies on, just
enforced by execution instead of by an enumerated menu. The backend
still validates the STRUCTURE of what Claude prints (never trust
model-authored JSON shape blindly) even though the VALUES inside it are
already trustworthy. See PROJECT_CONTEXT.md for the full reasoning,
including why the earlier enum-based design was replaced.
"""

import csv
import io
import json

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import AnalyticsQueryIn, AnalyticsQueryOut, ChartDatapointOut
from app.core.ai import call_claude, get_anthropic_client
from app.core.auth import get_current_tenant
from app.core.db import get_db
from app.db.models import CaseORM, TenantORM

router = APIRouter(prefix="/analytics", tags=["analytics"])

ANALYTICS_SYSTEM_PROMPT = """You are a data-analysis assistant helping a SACCO fraud auditor explore their case statistics. You have a Python code execution tool with pandas available.

Below is the tenant's real case data as CSV. Each row is one case; a case can trigger more than one rule (triggered_rules is a semicolon-separated list).

CASE DATA (CSV):
{case_data}

Rules — follow these exactly:
1. To answer the question, WRITE AND RUN Python code (pandas) that loads this CSV and computes the real answer. Never state a number without having actually computed it in code that ran — you are not allowed to estimate or eyeball a number from looking at the data.
2. Your code's FINAL print statement must be exactly one JSON object with this shape, and nothing else in that print call:
   {{"title": "<short chart title>", "chart_type": "bar" or "line", "data": [{{"label": "<string>", "value": <number>}}, ...]}}
3. Use chart_type "line" only when the x-axis is a real time sequence (e.g. grouped by date); use "bar" for any categorical breakdown.
4. Each case belongs to an analysis run (run_id column). For a snapshot question (e.g. "cases by severity" with no time aspect), use only the most recent run_id. For a trend/history question (e.g. "over time", "this month vs last"), use all runs.
5. If the question can't be answered from this data, still print valid JSON with an empty data list and a title explaining why.
6. The data given has already been stripped of case references and member names/IDs — work only with the columns provided. Never invent a case reference, member name, or ID that isn't in this data.
"""


def _cases_to_csv(rows: list[CaseORM]) -> str:
    """Privacy-minimized: no case_ref, subject_id, or subject_name - charts
    are about aggregates, never about identifying a specific member. Case
    Q&A and the report generator already own "tell me about this case"."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["run_id", "severity", "status", "subject_type", "triggered_rules", "risk_score", "created_at"])
    for r in rows:
        writer.writerow(
            [r.run_id, r.severity, r.status, r.subject_type, ";".join(r.triggered_rules), r.risk_score, r.created_at.isoformat()]
        )
    return buf.getvalue()


def _extract_chart(response) -> AnalyticsQueryOut | None:
    stdout = None
    for block in response.content:
        if block.type == "bash_code_execution_tool_result":
            result = block.content
            if getattr(result, "type", None) == "bash_code_execution_result" and result.return_code == 0:
                stdout = result.stdout  # keep the LAST successful execution's output

    if not stdout:
        return None

    parsed = None
    candidates = [stdout.strip()]
    lines = stdout.strip().splitlines()
    if lines:
        candidates.append(lines[-1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            break
        except ValueError:
            continue
    if not isinstance(parsed, dict):
        return None

    title = parsed.get("title")
    chart_type = parsed.get("chart_type")
    data = parsed.get("data")
    if not isinstance(title, str) or chart_type not in ("bar", "line") or not isinstance(data, list):
        return None

    points = []
    for item in data:
        if not isinstance(item, dict):
            return None
        label = item.get("label")
        value = item.get("value")
        if not isinstance(label, str) or not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        points.append(ChartDatapointOut(label=label, value=value))

    return AnalyticsQueryOut(title=title, chart_type=chart_type, data=points)


@router.post("/query", response_model=AnalyticsQueryOut)
def analytics_query(
    payload: AnalyticsQueryIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    rows = db.query(CaseORM).filter(CaseORM.tenant_id == tenant.id).all()
    if not rows:
        return AnalyticsQueryOut(title="No cases yet — run an analysis first.", chart_type="bar", data=[])

    system_prompt = ANALYTICS_SYSTEM_PROMPT.format(case_data=_cases_to_csv(rows))
    messages = [{"role": "user", "content": payload.question}]
    # No adaptive thinking, medium effort: writing one pandas aggregation
    # against a clearly-specified prompt is a bounded, mechanical task, not
    # one that benefits from deliberate reasoning - this cuts real latency
    # versus the default without giving up code-execution's flexibility.
    kwargs = dict(
        max_tokens=8192,
        output_config={"effort": "medium"},
        system=system_prompt,
        tools=[{"type": "code_execution_20260120", "name": "code_execution"}],
    )
    response = call_claude(client, messages=messages, **kwargs)

    # The server-side code-execution loop hit its iteration cap - resend to
    # continue. Per the documented pattern, no extra "Continue" message is
    # needed; the API detects the trailing server_tool_use and resumes.
    if response.stop_reason == "pause_turn":
        messages = [messages[0], {"role": "assistant", "content": response.content}]
        response = call_claude(client, messages=messages, **kwargs)

    chart = _extract_chart(response)
    if chart is None:
        raise HTTPException(status_code=502, detail="AI did not return a valid chart")
    return chart
