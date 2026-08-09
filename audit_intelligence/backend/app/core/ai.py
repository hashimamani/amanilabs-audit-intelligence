"""
Anthropic Claude client for the GenAI layer: case Q&A (routes/cases.py),
constrained-tool-use analytics (routes/analytics.py), and the board report
generator (routes/reports.py). ANTHROPIC_API_KEY has no safe default,
unlike JWT_SECRET/DATABASE_URL - it's a real paid external API, not
something safe to fake for local dev. get_anthropic_client checks the env
var directly, before ever touching the SDK, so an unset key fails clean
with a 503 instead of crashing on import or surfacing as a raw SDK auth
error deep in a route.

Client construction is a lazy, cached singleton rather than per-request:
anthropic.Anthropic() wraps a thread-safe httpx.Client connection pool, and
FastAPI runs sync routes in a threadpool, so sharing one client avoids
re-opening a connection per request - the same long-lived-resource shape as
core/db.py's engine/SessionLocal.
"""

import os
from functools import lru_cache

import anthropic
from fastapi import HTTPException

from app.db.models import CaseORM

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-opus-4-8"


@lru_cache(maxsize=1)
def _build_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def get_anthropic_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI features are not configured")
    return _build_client()


def call_claude(client: anthropic.Anthropic, **kwargs):
    """Translates Anthropic SDK exceptions into clean HTTP errors instead of
    letting them surface as a raw 500 traceback."""
    try:
        return client.messages.create(model=ANTHROPIC_MODEL, **kwargs)
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="AI service is rate-limited, try again shortly")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Could not reach the AI service")
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"AI service error: {e.message}")


def case_to_grounding_text(row: CaseORM) -> str:
    """Renders a case's evidence/flags/timeline/notes as verbatim, structured
    text for a system prompt - the same real data GET /cases/{id} returns,
    nothing new computed. Shared by case Q&A (one case) and the board report
    generator (many cases batched together)."""
    lines = [
        f"Case: {row.case_ref}",
        f"Subject: {row.subject_type} {row.subject_name} ({row.subject_id})",
        f"Severity: {row.severity}  Risk score: {row.risk_score}  Status: {row.status}",
        f"Triggered rules: {', '.join(row.triggered_rules) or 'none'}",
        "",
        "Evidence:",
    ]
    for e in row.evidence:
        lines.append(f"- {e['label']}: {e['value']}")

    lines += ["", "Flags:"]
    for f in row.flags:
        lines.append(f"- [{f['rule_id']}] {f['rule_name']} ({f['severity']}): {f['explanation']}")
        for e in f.get("evidence", []):
            lines.append(f"    evidence: {e['label']}: {e['value']}")
        if f.get("suggested_steps"):
            lines.append(f"    suggested steps: {'; '.join(f['suggested_steps'])}")

    lines += ["", "Timeline:"]
    for t in row.timeline:
        lines.append(f"- {t.get('timestamp', 'undated')}: {t.get('rule_name', '')} — {t.get('explanation', '')}")

    lines += ["", "Related entities:"]
    for k, v in row.related_entities.items():
        lines.append(f"- {k}: {', '.join(v)}")

    lines.append("")
    lines.append(f"Recommended actions: {'; '.join(row.recommended_actions) or 'none'}")
    lines.append(f"Auditor notes: {'; '.join(row.notes) or 'none'}")
    return "\n".join(lines)
