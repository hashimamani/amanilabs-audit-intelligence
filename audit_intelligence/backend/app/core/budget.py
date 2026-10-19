"""
A per-tenant daily ceiling on paid AI calls. Every case question, chart
and board report counts one; past the limit the route answers 429 before
any job is queued. One counter item per tenant per UTC day, expired by
DynamoDB's TTL a month later.

The count and the check are one conditional update, so two requests
arriving together cannot both squeeze under the limit. A request that AI
is not configured for (the 503 from get_anthropic_client) is not counted:
that dependency is resolved first.
"""

import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException

from app.core.ai import get_anthropic_client
from app.core.auth import get_current_tenant
from app.core.settings import get_settings
from app.db import repository as repo
from app.db.repository import Tenant

USAGE_RETENTION_DAYS = 31


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _usage_key() -> str:
    return f"ai#{_today()}"


def ai_calls_today(tenant_slug: str) -> int:
    return repo.get_usage(tenant_slug, _usage_key())


def record_ai_call(tenant_slug: str, limit: int) -> int:
    """Counts one call, or raises UsageLimitReached without counting it."""
    expires = int(time.time()) + USAGE_RETENTION_DAYS * 86400
    return repo.increment_usage(tenant_slug, _usage_key(), expires_at=expires, limit=limit)


def enforce_ai_budget(
    tenant: Tenant = Depends(get_current_tenant),
    _client=Depends(get_anthropic_client),
) -> Tenant:
    limit = get_settings().ai_daily_limit
    try:
        record_ai_call(tenant.slug, limit)
    except repo.UsageLimitReached:
        raise HTTPException(
            status_code=429,
            detail=(
                f"This SACCO's daily AI allowance ({limit} questions, charts and reports) "
                "is used up. It resets at midnight UTC."
            ),
        )
    return tenant
