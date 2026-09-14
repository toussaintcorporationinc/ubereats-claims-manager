import json
import time
import logging
from dataclasses import asdict
from datetime import date, timedelta
from secrets import compare_digest
from typing import Annotated

import jwt
from jwt import PyJWKClient
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import AuditLog, User
from app.services.audit import add_audit_log
from app.services.autopilot_service import AutopilotError, run_autopilot
from app.services.email_provider import EmailProviderError
from app.services.gmail_email_provider import GmailEmailProvider
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService
from app.services.gmail_inbound_sync_service import GmailInboundSyncService
from app.services.runtime_settings_service import get_runtime_bool_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])
# GitHub Actions OIDC workers trigger these runtime routes.

HISTORICAL_BACKFILL_START = date(2026, 1, 1)
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_JWKS_URI = "https://token.actions.githubusercontent.com/.well-known/jwks"
GITHUB_OIDC_AUDIENCE = "tennet-runtime"
GITHUB_OIDC_REPOSITORY = "toussaintcorporationinc/ubereats-claims-manager"
GITHUB_OIDC_ALLOWED_WORKFLOW_REFS = {
    f"{GITHUB_OIDC_REPOSITORY}/.github/workflows/tennet-gmail-sync.yml@refs/heads/main",
    f"{GITHUB_OIDC_REPOSITORY}/.github/workflows/tennet-gmail-backfill.yml@refs/heads/main",
    f"{GITHUB_OIDC_REPOSITORY}/.github/workflows/tennet-followup-worker.yml@refs/heads/main",
}


def _valid_github_actions_runtime_token(token: str) -> bool:
    try:
        signing_key = PyJWKClient(GITHUB_OIDC_JWKS_URI).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=GITHUB_OIDC_AUDIENCE,
            issuer=GITHUB_OIDC_ISSUER,
            options={
                "require": [
                    "exp",
                    "iat",
                    "iss",
                    "aud",
                    "repository",
                    "ref",
                    "workflow_ref",
                ]
            },
        )
    except Exception as exc:
        try:
            safe_claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "verify_exp": False,
                },
            )
        except Exception:
            safe_claims = {}
        logger.warning(
            "GitHub OIDC validation failed: %s: %s; iss=%r aud=%r repository=%r ref=%r workflow_ref=%r",
            type(exc).__name__,
            str(exc)[:300],
            safe_claims.get("iss"),
            safe_claims.get("aud"),
            safe_claims.get("repository"),
            safe_claims.get("ref"),
            safe_claims.get("workflow_ref"),
        )
        return False

    allowed = (
        claims.get("repository") == GITHUB_OIDC_REPOSITORY
        and claims.get("ref") == "refs/heads/main"
        and claims.get("workflow_ref") in GITHUB_OIDC_ALLOWED_WORKFLOW_REFS
    )
    if not allowed:
        logger.warning(
            "GitHub OIDC claims rejected: repository=%r ref=%r workflow_ref=%r aud=%r iss=%r",
            claims.get("repository"),
            claims.get("ref"),
            claims.get("workflow_ref"),
            claims.get("aud"),
            claims.get("iss"),
        )
    return allowed


def _require_runtime_authorization(authorization: str | None) -> None:
    if authorization and authorization.startswith("Bearer "):
        bearer_token = authorization.removeprefix("Bearer ").strip()
        if bearer_token and _valid_github_actions_runtime_token(bearer_token):
            return

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
    settings = get_settings()
    runtime_enabled = get_runtime_bool_setting(db, "gmail_automation_enabled", False)
    if runtime_enabled:
        settings = settings.model_copy(
            update={
                "email_provider_enabled": True,
                "gmail_inbound_sync_enabled": True,
                "gmail_inbound_auto_sync_enabled": True,
                "gmail_inbound_auto_sync_run_autopilot": True,
            }
        )
    result = GmailInboundAutoSyncService(
        provider=GmailEmailProvider(trusted_runtime=runtime_enabled),
        settings=settings,
    ).sync_due_accounts(db)
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

    owner = None
    last_db_error: SQLAlchemyError | None = None
    for attempt in range(3):
        try:
            owner = db.scalar(
                select(User)
                .where(User.active.is_(True), User.role == "owner")
                .order_by(User.id)
            )
            last_db_error = None
            break
        except SQLAlchemyError as exc:
            last_db_error = exc
            db.rollback()
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    if last_db_error is not None:
        raw_error = str(getattr(last_db_error, "orig", last_db_error)).replace("\n", " ").strip()
        if "password=" in raw_error.casefold():
            raw_error = "database_connection_failed"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed after retries: {raw_error[:500]}",
        )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active TENNET owner is configured",
        )

    service = GmailInboundSyncService(GmailEmailProvider(trusted_runtime=True))
    account, day = _next_backfill_target(db, service, owner)
    if account is None or day is None:
        return {
            "status": "complete",
            "start_date": HISTORICAL_BACKFILL_START.isoformat(),
            "end_date": date.today().isoformat(),
        }

    next_day = day + timedelta(days=1)
    query = f"after:{day.strftime('%Y/%m/%d')} before:{next_day.strftime('%Y/%m/%d')}"
    try:
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
    except EmailProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        db.rollback()
        safe_error = str(exc).replace("\n", " ").strip()
        if "password=" in safe_error.casefold():
            safe_error = "database_or_provider_error"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{type(exc).__name__}: {safe_error[:500]}",
        ) from exc

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



def _run_followup_worker(
    authorization: str | None,
    db: Session,
) -> dict[str, object]:
    _require_runtime_authorization(authorization)

    owner = None
    last_db_error: SQLAlchemyError | None = None
    for attempt in range(3):
        try:
            owner = db.scalar(
                select(User)
                .where(User.active.is_(True), User.role == "owner")
                .order_by(User.id)
            )
            last_db_error = None
            break
        except SQLAlchemyError as exc:
            last_db_error = exc
            db.rollback()
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
    if last_db_error is not None:
        raw_error = str(getattr(last_db_error, "orig", last_db_error)).replace("\n", " ").strip()
        if "password=" in raw_error.casefold():
            raw_error = "database_connection_failed"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed after retries: {raw_error[:500]}",
        )
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active TENNET owner is configured",
        )

    try:
        result = run_autopilot(
            db,
            owner,
            mode="followups",
            restaurant_id=None,
            dry_run=False,
            provider=GmailEmailProvider(trusted_runtime=True),
            max_candidates=4,
            trusted_runtime_followups=True,
        )
    except AutopilotError as exc:
        db.rollback()
        if exc.message in {
            "gmail_account_not_connected",
            "email_provider_disabled",
            "gmail_oauth_not_configured",
            "gmail_oauth_client_secret_not_configured",
        }:
            return {
                "status": "blocked",
                "run_id": None,
                "total_candidates": 0,
                "sent_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "error_message": exc.message,
            }
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    payload = {
        "status": result.run.status,
        "run_id": result.run.id,
        "total_candidates": result.run.total_candidates,
        "sent_count": result.run.sent_count,
        "skipped_count": result.run.skipped_count,
        "failed_count": result.run.failed_count,
        "error_message": result.run.error_message,
    }
    db.commit()
    return payload




@router.api_route("/followup-worker", methods=["GET", "POST"])
def run_followup_worker(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _run_followup_worker(authorization, db)


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
