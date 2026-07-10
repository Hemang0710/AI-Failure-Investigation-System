"""Per-client rate limiting, enforced as FastAPI dependencies.

Limits are keyed by the presented API key (hashed) so tenants don't share
buckets; unauthenticated requests fall back to the client IP. Storage is
in-memory per process - point RATE_LIMIT_STORAGE_URI at Redis when running
more than one backend instance.

Implemented directly on the `limits` library (rather than slowapi) because
dependency-based enforcement survives Starlette routing changes and, like
auth, cannot be silently skipped for a route.
"""

import hashlib
import math
import os
import time

from fastapi import HTTPException, Request, status
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter

RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
RATE_LIMIT_INGEST = os.getenv("RATE_LIMIT_INGEST", "30/minute")
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"

_storage = storage_from_string(os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"))
_strategy = MovingWindowRateLimiter(_storage)


def _client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return "key:" + hashlib.sha256(parts[1].encode("utf-8")).hexdigest()[:32]
    host = request.client.host if request.client else "unknown"
    return "ip:" + host


def rate_limiter(limit_str: str, scope: str):
    """Build a dependency enforcing `limit_str` (e.g. "120/minute") per client.

    Each scope is a separate bucket, so a route-specific limiter stacks with
    the router-wide default.
    """
    limit_item = parse(limit_str)

    async def _dependency(request: Request) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        key = _client_key(request)
        if not _strategy.hit(limit_item, key, scope):
            stats = _strategy.get_window_stats(limit_item, key, scope)
            retry_after = max(1, math.ceil(stats.reset_time - time.time()))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {limit_item}",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency


default_rate_limit = rate_limiter(RATE_LIMIT_DEFAULT, "default")
ingest_rate_limit = rate_limiter(RATE_LIMIT_INGEST, "ingest")
