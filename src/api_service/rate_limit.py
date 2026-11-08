"""Call limit of the login routes (per client IP, per process).

A sliding window of ``Settings.sso_rate_limit_per_minute`` calls; over it
the route answers 429 with ``Retry-After``. 0 turns it off.
"""

import time
from collections import deque

from fastapi import HTTPException, Request

WINDOW_SECONDS = 60.0
_calls: dict[str, deque[float]] = {}


def client_ip(request: Request) -> str:
    """The first ``X-Forwarded-For`` hop (the ingress), else the peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",", 1)[0].strip()
    if first:
        return first
    return request.client.host if request.client else "-"


async def sso_rate_limit(request: Request) -> None:
    limit = request.app.state.services.settings.sso_rate_limit_per_minute
    if limit <= 0:
        return
    now = time.monotonic()
    if len(_calls) > 10000:
        _calls.clear()
    calls = _calls.setdefault(client_ip(request), deque())
    while calls and calls[0] <= now - WINDOW_SECONDS:
        calls.popleft()
    if len(calls) >= limit:
        retry = max(1, int(calls[0] + WINDOW_SECONDS - now) + 1)
        raise HTTPException(
            429,
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry)},
        )
    calls.append(now)
