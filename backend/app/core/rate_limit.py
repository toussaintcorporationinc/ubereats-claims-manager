from __future__ import annotations

from threading import Lock
from time import monotonic

from fastapi import Request

from app.core.config import get_settings

WINDOW_SECONDS = 60.0

_lock = Lock()
_requests: dict[tuple[str, str], list[float]] = {}


def reset_rate_limit_state() -> None:
    with _lock:
        _requests.clear()


def is_rate_limited(request: Request) -> bool:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return False

    path = request.url.path
    limit = settings.login_rate_limit_per_minute if path == "/v1/auth/login" else settings.rate_limit_requests_per_minute
    if limit <= 0:
        return False

    client_host = request.client.host if request.client else "unknown"
    key = (client_host, path if path == "/v1/auth/login" else "*")
    now = monotonic()
    cutoff = now - WINDOW_SECONDS

    with _lock:
        hits = [timestamp for timestamp in _requests.get(key, []) if timestamp >= cutoff]
        if len(hits) >= limit:
            _requests[key] = hits
            return True
        hits.append(now)
        _requests[key] = hits
        return False
