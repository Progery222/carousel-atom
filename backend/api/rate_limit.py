"""Rate limiting for the public /api/v1 router.

Uses slowapi's in-memory backend. Per-key (or per-IP if anonymous) limits
that reset every minute. Two tiers:

- HEAVY ("30/minute" by default) — render endpoints and ZIP export.
- LIGHT ("120/minute") — discovery and preview endpoints (cheap).

Override the heavy tier via the `CAROUSEL_API_RATE_LIMIT` env var.
"""
from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _identify(request: Request) -> str:
    """Bucket key: API-key name if authenticated, IP otherwise."""
    info = getattr(request.state, "api_key", None)
    if info is not None:
        return f"key:{info.name}"
    return f"ip:{get_remote_address(request)}"


HEAVY_LIMIT = os.environ.get("CAROUSEL_API_RATE_LIMIT", "30/minute")
LIGHT_LIMIT = os.environ.get("CAROUSEL_API_RATE_LIMIT_LIGHT", "120/minute")

# key_style="endpoint" tells slowapi to bucket counters by the endpoint
# function name instead of the resolved URL path. Without this, dynamic
# segments (e.g. /export/{run_id}.zip) create a fresh counter per unique
# run_id and the limit never trips.
limiter = Limiter(key_func=_identify, default_limits=[], key_style="endpoint")
