from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone


GMAIL_RETRY_AFTER_RE = re.compile(
    r"(?:Retry after|gmail_quota_retry_after:)\s*([0-9T:Z+\-.]+)",
    re.IGNORECASE,
)


def parse_gmail_retry_after(
    error_message: str | None,
    *,
    safety_seconds: int = 0,
    now: datetime | None = None,
) -> datetime | None:
    if not error_message:
        return None

    lowered = error_message.casefold()
    # Gmail sometimes returns quota exhaustion without a Retry-After timestamp
    # (notably PERMISSION_DENIED / Total Query Cost per user). Treat that as a
    # short per-account backoff instead of hammering the API for every candidate.
    if (
        "quota exceeded" in lowered
        or "userratelimitexceeded" in lowered
        or "ratelimitexceeded" in lowered
        or "total query cost" in lowered
    ):
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        return current_time + timedelta(seconds=90 + max(safety_seconds, 0))

    match = GMAIL_RETRY_AFTER_RE.search(error_message)
    if match is None:
        return None

    raw_value = match.group(1).strip().rstrip(".,;)")
    try:
        retry_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    retry_at = retry_at.astimezone(timezone.utc)
    if safety_seconds > 0:
        retry_at += timedelta(seconds=safety_seconds)

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if retry_at <= current_time:
        return None
    return retry_at


def parse_gmail_retry_after_from_errors(
    errors: Iterable[str],
    *,
    safety_seconds: int = 0,
    now: datetime | None = None,
) -> datetime | None:
    retry_dates = [
        retry_at
        for error in errors
        if (retry_at := parse_gmail_retry_after(error, safety_seconds=safety_seconds, now=now)) is not None
    ]
    if not retry_dates:
        return None
    return max(retry_dates)


def seconds_until_gmail_retry(retry_at: datetime | None, *, now: datetime | None = None) -> int | None:
    if retry_at is None:
        return None
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return max(0, int((retry_at - current_time).total_seconds()))
