"""
Constrained "ask for a chart" analytics. Claude never sees raw case data,
never writes SQL, and never states a number itself - it only picks WHICH of
a small, fixed set of server-computed aggregations (via a single forced
tool call) answers the auditor's question. The backend re-validates the
tool call's params against the same literal enum before running anything
(defense in depth - never trust a model-supplied string blindly, even
though tool_choice already constrains the schema), then computes and
labels the real numbers itself. See PROJECT_CONTEXT.md for the full
reasoning tying this back to the product's "never invent evidence" rule.
"""

from collections import Counter

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import AnalyticsQueryIn, AnalyticsQueryOut, ChartDatapointOut
from app.core.ai import call_claude, get_anthropic_client
from app.core.auth import get_current_tenant
from app.core.db import get_db
from app.db.models import AnalysisRunORM, CaseORM, TenantORM

router = APIRouter(prefix="/analytics", tags=["analytics"])

GROUP_BY_VALUES = ["severity", "status", "subject_type", "rule_id", "created_date"]
METRIC_VALUES = ["case_count"]

TITLES = {
    "severity": "Cases by severity",
    "status": "Cases by status",
    "subject_type": "Cases by subject type",
    "rule_id": "Cases per triggered rule (a case may count toward more than one rule)",
    "created_date": "Cases by creation date",
}

# Chart type is derived from the dimension, never chosen by Claude - keeps
# the "model only picks WHICH real thing, never decides presentation" rule
# intact. created_date is inherently a time series; everything else is a
# categorical snapshot.
CHART_TYPE = {
    "severity": "bar",
    "status": "bar",
    "subject_type": "bar",
    "rule_id": "bar",
    "created_date": "line",
}

ANALYTICS_SYSTEM_PROMPT = (
    "You help an auditor explore fraud-case statistics. You never compute or "
    "state any number yourself. Your only job is to call generate_chart, "
    "picking the group_by and metric that best answer the user's question "
    "from the fixed set the tool defines. If nothing fits well, pick the "
    "closest reasonable option."
)

GENERATE_CHART_TOOL = {
    "name": "generate_chart",
    "description": (
        "Select the pre-defined, server-computed aggregation that answers the "
        "user's question about their fraud-audit case data. You do not compute "
        "numbers yourself — you only choose which aggregation to run."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "group_by": {
                "type": "string",
                "enum": GROUP_BY_VALUES,
                "description": (
                    "'severity' = case severity (Low/Medium/High/Critical). "
                    "'status' = case status (Open/In Progress/Closed). "
                    "'subject_type' = whether the case's subject is a member or "
                    "an employee. 'rule_id' = which fraud-detection rule "
                    "triggered the case — a case can trigger more than one "
                    "rule, so these counts can exceed the total case count. "
                    "'created_date' = the case's creation date, by day."
                ),
            },
            "metric": {
                "type": "string",
                "enum": METRIC_VALUES,
                "description": "What to measure per group. Only case_count exists in v1.",
            },
        },
        "required": ["group_by", "metric"],
    },
}


def _latest_run_id(db: Session, tenant_id: int) -> int | None:
    latest = (
        db.query(AnalysisRunORM)
        .filter(AnalysisRunORM.tenant_id == tenant_id)
        .order_by(AnalysisRunORM.created_at.desc())
        .first()
    )
    return latest.id if latest else None


@router.post("/query", response_model=AnalyticsQueryOut)
def analytics_query(
    payload: AnalyticsQueryIn,
    db: Session = Depends(get_db),
    tenant: TenantORM = Depends(get_current_tenant),
    client: anthropic.Anthropic = Depends(get_anthropic_client),
):
    response = call_claude(
        client,
        max_tokens=256,
        system=ANALYTICS_SYSTEM_PROMPT,
        tools=[GENERATE_CHART_TOOL],
        tool_choice={"type": "tool", "name": "generate_chart"},
        messages=[{"role": "user", "content": payload.question}],
    )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None or tool_use.name != "generate_chart":
        raise HTTPException(status_code=502, detail="AI did not return a valid chart request")

    params = tool_use.input if isinstance(tool_use.input, dict) else {}
    group_by = params.get("group_by")
    metric = params.get("metric")
    if group_by not in GROUP_BY_VALUES or metric not in METRIC_VALUES:
        raise HTTPException(status_code=400, detail="Unsupported chart request from AI")

    # created_date is a time series - it should span the tenant's whole case
    # history, not just the latest run. A single analysis run creates all its
    # cases in one batch, so scoping it to "latest run only" (like every
    # other dimension, which IS the correct scope for a snapshot breakdown)
    # would show one spike on one day instead of a trend.
    if group_by == "created_date":
        rows = db.query(CaseORM).filter(CaseORM.tenant_id == tenant.id).all()
    else:
        run_id = _latest_run_id(db, tenant.id)
        rows = (
            db.query(CaseORM)
            .filter(CaseORM.tenant_id == tenant.id, CaseORM.run_id == run_id)
            .all()
            if run_id is not None
            else []
        )

    counts: Counter = Counter()
    if group_by == "rule_id":
        for row in rows:
            for rule_id in row.triggered_rules:
                counts[rule_id] += 1
    elif group_by == "created_date":
        for row in rows:
            counts[row.created_at.date().isoformat()] += 1
    else:
        for row in rows:
            counts[getattr(row, group_by)] += 1

    data = [ChartDatapointOut(label=label, value=value) for label, value in sorted(counts.items())]
    return AnalyticsQueryOut(
        title=TITLES[group_by],
        group_by=group_by,
        metric=metric,
        chart_type=CHART_TYPE[group_by],
        data=data,
    )
