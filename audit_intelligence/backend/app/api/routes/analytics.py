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
import logging

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import AnalyticsQueryIn, AnalyticsQueryOut, ChartDatapointOut
from app.core.ai import call_claude, get_anthropic_client
from app.core.auth import get_current_tenant
from app.core.db import get_db
from app.db.models import CaseORM, TenantORM

router = APIRouter(prefix="/analytics", tags=["analytics"])

logger = logging.getLogger(__name__)

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

CONCISE_RETRY_SUFFIX = """

IMPORTANT: a previous attempt at this question ran out of output budget before finishing. This time, be maximally concise: write the minimum code needed to answer the question, do not print any exploratory or intermediate output, and make your ONLY print statement the final JSON object described above."""


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
    stripped = stdout.strip()
    lines = stripped.splitlines()
    candidates = [stripped]
    if lines:
        candidates.append(lines[-1])
        # The system prompt only requires the FINAL print to be pure JSON -
        # it explicitly allows earlier exploratory prints (e.g. a df.head()
        # sanity check) in the same execution. Neither candidate above
        # handles that (candidate 1 breaks on any extra output, candidate 2
        # only catches a single-line final print), nor a pretty-printed
        # multi-line JSON print. Added after an unreproduced production 502
        # ("AI did not return a valid chart") with no diagnostic logging at
        # the time - this is the most plausible gap on a close read of the
        # parsing logic, not a confirmed root cause. _debug_summary logs
        # full stdout/stderr on any future failure so the next occurrence
        # is actually diagnosable instead of guessed at.
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].lstrip().startswith("{"):
                candidates.append("\n".join(lines[i:]))
                break
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


def _debug_summary(response) -> str:
    """Only called on the failure path (_extract_chart returned None) - the
    502 this guards gave zero diagnostic signal in production logs, so the
    first real occurrence couldn't be root-caused. Summarizes stop_reason
    plus every content block (truncated) so the next occurrence is
    debuggable without needing to reproduce it live again."""
    parts = [f"stop_reason={response.stop_reason!r}", f"usage={getattr(response, 'usage', None)!r}"]
    for block in response.content:
        btype = getattr(block, "type", "?")
        if btype == "bash_code_execution_tool_result":
            result = block.content
            rtype = getattr(result, "type", "?")
            if rtype == "bash_code_execution_result":
                stdout = (getattr(result, "stdout", "") or "")[:2000]
                stderr = (getattr(result, "stderr", "") or "")[:2000]
                parts.append(
                    f"[{btype}] return_code={getattr(result, 'return_code', '?')} "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            else:
                parts.append(f"[{btype}] result_type={rtype!r} content={str(result)[:1000]!r}")
        elif btype == "text":
            parts.append(f"[text] {getattr(block, 'text', '')[:1000]!r}")
        elif btype == "server_tool_use":
            parts.append(f"[server_tool_use] input={str(getattr(block, 'input', ''))[:500]!r}")
        else:
            parts.append(f"[{btype}] {str(block)[:500]!r}")
    return "\n".join(parts)


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

    base_system_prompt = ANALYTICS_SYSTEM_PROMPT.format(case_data=_cases_to_csv(rows))
    user_message = {"role": "user", "content": payload.question}
    # Sonnet, not the app-wide default Opus: chart generation is
    # latency-sensitive (a live user is waiting on it), and writing one
    # pandas aggregation from a clearly-specified prompt doesn't need
    # Opus-level intelligence. thinking is explicitly disabled rather than
    # omitted - Sonnet 5 defaults to adaptive thinking when thinking is
    # omitted (unlike Opus 4.8, which defaults to no thinking), so leaving
    # it out here would silently reintroduce the reasoning overhead this
    # is trying to avoid.
    kwargs = dict(
        model="claude-sonnet-5",
        max_tokens=12000,
        thinking={"type": "disabled"},
        output_config={"effort": "medium"},
        system=base_system_prompt,
        tools=[{"type": "code_execution_20260120", "name": "code_execution"}],
    )
    messages = [user_message]
    response = call_claude(client, messages=messages, **kwargs)

    # The server-side code-execution loop hit its iteration cap - resend to
    # continue. Per the documented pattern, no extra "Continue" message is
    # needed; the API detects the trailing server_tool_use and resumes.
    if response.stop_reason == "pause_turn":
        messages = [messages[0], {"role": "assistant", "content": response.content}]
        response = call_claude(client, messages=messages, **kwargs)

    if response.stop_reason == "max_tokens":
        # Found live in production on a compound question ("trend of
        # Critical cases this month" - a time filter AND a severity filter
        # AND a trend grouping): the model ran out of output budget before
        # finishing its code, sometimes with very little visible content
        # written yet. Unlike pause_turn, a max_tokens cutoff isn't a
        # documented resumable state (the trailing content can end mid
        # tool-input, not a well-formed block to replay), so retry as a
        # FRESH call rather than trying to continue it - with an explicit
        # instruction to be concise, since a verbose/exploratory first
        # attempt is the most likely way a single chart question burns
        # through 12000 output tokens.
        retry_kwargs = {**kwargs, "system": base_system_prompt + CONCISE_RETRY_SUFFIX}
        retry_messages = [user_message]
        response = call_claude(client, messages=retry_messages, **retry_kwargs)
        if response.stop_reason == "pause_turn":
            retry_messages = [retry_messages[0], {"role": "assistant", "content": response.content}]
            response = call_claude(client, messages=retry_messages, **retry_kwargs)

    chart = _extract_chart(response)
    if chart is None:
        logger.warning(
            "analytics_query: AI did not return a valid chart. question=%r tenant_id=%s\n%s",
            payload.question,
            tenant.id,
            _debug_summary(response),
        )
        if response.stop_reason == "max_tokens":
            raise HTTPException(
                status_code=502,
                detail="This question needed more analysis than fits in one response — try asking something more specific or narrower (e.g. one filter at a time).",
            )
        raise HTTPException(status_code=502, detail="AI did not return a valid chart")
    return chart
