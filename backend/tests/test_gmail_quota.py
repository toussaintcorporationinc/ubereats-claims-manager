from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.models import GmailSyncState
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService
from app.services.gmail_quota import parse_gmail_retry_after, seconds_until_gmail_retry


def test_parse_gmail_retry_after_from_provider_error() -> None:
    now = datetime(2026, 6, 26, 0, 0, tzinfo=timezone.utc)

    retry_at = parse_gmail_retry_after(
        "Gmail API error: RESOURCE_EXHAUSTED. Retry after 2026-06-26T00:01:38Z",
        now=now,
    )

    assert retry_at == datetime(2026, 6, 26, 0, 1, 38, tzinfo=timezone.utc)
    assert seconds_until_gmail_retry(retry_at, now=now) == 98


def test_parse_gmail_retry_after_from_internal_monitor_marker() -> None:
    now = datetime(2026, 6, 26, 0, 0, tzinfo=timezone.utc)

    retry_at = parse_gmail_retry_after(
        "gmail_quota_retry_after:2026-06-26T00:03:00+00:00",
        now=now,
    )

    assert retry_at == datetime(2026, 6, 26, 0, 3, tzinfo=timezone.utc)


def test_auto_sync_skips_account_until_gmail_retry_after() -> None:
    now = datetime(2026, 6, 26, 0, 0, tzinfo=timezone.utc)
    service = GmailInboundAutoSyncService(
        settings=Settings(
            gmail_inbound_auto_sync_continuous_enabled=True,
            gmail_quota_retry_safety_seconds=0,
        )
    )
    sync_state = GmailSyncState(
        status="failed",
        last_error="Gmail quota reached. Retry after 2026-06-26T00:01:38Z",
    )

    assert service.account_is_due(sync_state, now) is False
