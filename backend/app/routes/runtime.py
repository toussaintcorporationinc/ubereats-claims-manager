import json
from dataclasses import asdict
from datetime import date, timedelta
from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import AuditLog, User
from app.services.audit import add_audit_log
from app.services.gmail_email_provider import GmailEmailProvider
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService
from app.services.gmail_inbound_sync_service import GmailInboundSyncService

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])

HISTORICAL_BACKFILL_START = date(2026, 1, 1)


def _require_runtime_authorization(authorization: str | None) -> None:
    settings = get_settings()
    secrets_to_try = [value for value in (settings.tennet_cron_secret, settings.cron_secret) if value]
    if not secrets_to_try:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime sync is not configured",
        )

    if authorization is None or not any(
        compare_digest(authorization, f"Bearer {secret}") for secret in secrets_to_try
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid runtime token")


def _run_gmail_sync(
    authorization: str | None,
    db: Session,
) -> dict[str, object]:
    _require_runtime_authorization(authorization)
    result = GmailInboundAutoSyncService(settings=get_settings()).sync_due_accounts(db)
    db.commit()
    return asdict(result)


def _completed_backfill_days(db: Session, email_account_id: int) -> set[str]:
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "email_account",
            AuditLog.entity_id == email_account_id,
            AuditLog.action == "gmail_historical_backfill.day_completed",
        )
        .order_by(AuditLog.id)
    ).all()
    completed: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(row.new_value or "{}")
        except (TypeError, ValueError):
            continue
        day = payload.get("day")
        if isinstance(day, str):
            completed.add(day)
    return completed


def _next_backfill_target(db: Session, service: GmailInboundSyncService, owner: User):
    accounts = service.get_active_accounts(db, owner)
    if not accounts:
        return None, None

    today = date.today()
    completed_by_account = {
        account.id: _completed_backfill_days(db, account.id)
        for account in accounts
    }
    day = HISTORICAL_BACKFILL_START
    while day <= today:
        day_key = day.isoformat()
        for account in accounts:
            if day_key not in completed_by_account[account.id]:
                return account, day
        day += timedelta(days=1)
    return None, None


def _run_gmail_backfill(
    authorization: str | None,
    db: Session,
) -> dict[str, object]:
    _require_runtime_authorization(authorization)

    owner = db.scalar(
        select(User)
        .where(User.active.is_(True), User.role == "owner")
        .order_by(User.id)
    )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active TENNET owner is configured",
        )

    service = GmailInboundSyncService(GmailEmailProvider())
    account, day = _next_backfill_target(db, service, owner)
    if account is None or day is None:
        return {
            "status": "complete",
            "start_date": HISTORICAL_BACKFILL_START.isoformat(),
            "end_date": date.today().isoformat(),
        }

    next_day = day + timedelta(days=1)
    query = f"after:{day.strftime('%Y/%m/%d')} before:{next_day.strftime('%Y/%m/%d')}"
    result = service.sync_account(
        db,
        owner,
        account,
        lookback_days=365,
        max_messages=500,
        analyze_responses=True,
        apply_reviews=True,
        reprocess_existing_limit=500,
        query_override=query,
        full_history=True,
        include_starred_discovery=False,
    )

    payload = {
        "day": day.isoformat(),
        "email_account_id": account.id,
        "email_address": account.email_address,
        "status": result.status,
        "synced_messages": result.synced_messages,
        "linked_messages": result.linked_messages,
        "unlinked_messages": result.unlinked_messages,
        "ignored_messages": result.ignored_messages,
        "analyzed_messages": result.analyzed_messages,
        "applied_reviews": result.applied_reviews,
        "negative_responses_detected": result.negative_responses_detected,
        "errors": result.errors[:20],
    }
    add_audit_log(
        db,
        entity_type="email_account",
        entity_id=account.id,
        action=(
            "gmail_historical_backfill.day_completed"
            if result.status == "success"
            else "gmail_historical_backfill.day_failed"
        ),
        user_id=owner.id,
        new_value=payload,
    )
    db.commit()
    return payload


@router.api_route("/gmail-sync", methods=["GET", "POST"])
def run_gmail_sync(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _run_gmail_sync(authorization, db)


@router.api_route("/gmail-backfill", methods=["GET", "POST"])
def run_gmail_backfill(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _run_gmail_backfill(authorization, db)
