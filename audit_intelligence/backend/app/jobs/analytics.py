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
already trustworthy. See PROJECT_CONTEXT.md for the full reasoning.

Runs as a background job: the round trip is 30-60s, longer than any
gateway timeout.
"""

import csv
import io
import json

from app.core.ai import call_claude, get_anthropic_client
from app.core.logging import logger
from app.db import repository as repo
from app.jobs.service import JobFailed

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

EMPTY_CHART = {"title": "No cases yet — run an analysis first.", "chart_type": "bar", "data": []}


def cases_to_csv(rows: list[dict]) -> str:
    """Privacy-minimized: no case_ref, subject_id, or subject_name - charts
    are about aggregates, never about identifying a specific member."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["run_id", "severity", "status", "subject_type", "triggered_rules", "risk_score", "created_at"])
    for r in rows:
        writer.writerow([
            r["run_id"], r["severity"], r["status"], r["subject_type"],
            ";".join(r.get("triggered_rules", [])), r["risk_score"], r["created_at"],
        ])
    return buf.getvalue()


def extract_chart(response) -> dict | None:
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
        # The prompt only requires the FINAL print to be pure JSON; earlier
        # exploratory prints and pretty-printed multi-line JSON both happen.
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
        points.append({"label": label, "value": float(value)})

    return {"title": title, "chart_type": chart_type, "data": points}


def debug_summary(response) -> str:
    parts = [f"stop_reason={response.stop_reason!r}", f"usage={getattr(response, 'usage', None)!r}"]
    for block in response.content:
        btype = getattr(block, "type", "?")
        if btype == "bash_code_execution_tool_result":
            result = block.content
            rtype = getattr(result, "type", "?")
            if rtype == "bash_code_execution_result":
                stdout = (getattr(result, "stdout", "") or "")[:2000]
                stderr = (getattr(result, "stderr", "") or "")[:2000]
                parts.append(f"[{btype}] return_code={getattr(result, 'return_code', '?')} stdout={stdout!r} stderr={stderr!r}")
            else:
                parts.append(f"[{btype}] result_type={rtype!r} content={str(result)[:1000]!r}")
        elif btype == "text":
            parts.append(f"[text] {getattr(block, 'text', '')[:1000]!r}")
        elif btype == "server_tool_use":
            parts.append(f"[server_tool_use] input={str(getattr(block, 'input', ''))[:500]!r}")
        else:
            parts.append(f"[{btype}] {str(block)[:500]!r}")
    return "\n".join(parts)


def run_analytics(tenant_slug: str, question: str, client) -> dict:
    rows = repo.list_case_analytics_rows(tenant_slug)
    if not rows:
        return EMPTY_CHART

    base_system_prompt = ANALYTICS_SYSTEM_PROMPT.format(case_data=cases_to_csv(rows))
    user_message = {"role": "user", "content": question}
    # Sonnet, not the app-wide Opus default: a live user is waiting, and one
    # pandas aggregation from a precise prompt does not need Opus. thinking
    # is explicitly disabled - Sonnet 5 defaults to adaptive thinking when it
    # is omitted, which would silently reintroduce the latency this avoids.
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

    if response.stop_reason == "pause_turn":
        messages = [messages[0], {"role": "assistant", "content": response.content}]
        response = call_claude(client, messages=messages, **kwargs)

    if response.stop_reason == "max_tokens":
        # Not a resumable state (the tail can end mid tool-input), so retry
        # fresh with an instruction to be concise.
        retry_kwargs = {**kwargs, "system": base_system_prompt + CONCISE_RETRY_SUFFIX}
        retry_messages = [user_message]
        response = call_claude(client, messages=retry_messages, **retry_kwargs)
        if response.stop_reason == "pause_turn":
            retry_messages = [retry_messages[0], {"role": "assistant", "content": response.content}]
            response = call_claude(client, messages=retry_messages, **retry_kwargs)

    chart = extract_chart(response)
    if chart is None:
        logger.warning("analytics: AI did not return a valid chart", question=question, tenant_slug=tenant_slug, detail=debug_summary(response))
        if response.stop_reason == "max_tokens":
            raise JobFailed(
                "This question needed more analysis than fits in one response — try asking something more specific or narrower (e.g. one filter at a time)."
            )
        raise JobFailed("AI did not return a valid chart")
    return chart


def run_analytics_job(tenant_slug: str, job: dict) -> dict:
    return run_analytics(tenant_slug, job["payload"]["question"], get_anthropic_client())
