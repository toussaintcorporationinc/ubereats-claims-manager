import json
import time
import logging
from collections import Counter
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
from app.models import AuditLog, ClaimOrder, FollowUpTask, Restaurant, User
from app.models.domain import utc_now
from app.services.audit import add_audit_log
from app.services.autopilot_service import (
    FOLLOWUP_ACTION_BY_TASK,
    AutopilotError,
    followup_skip_reason,
    repair_followup_queue,
    run_autopilot,
)
from app.services.customer_refund_autopilot_service import run_customer_refund_autopilot
from app.services.email_provider import EmailProviderError
from app.services.gmail_email_provider import GmailEmailProvider
from app.services.gmail_inbound_auto_sync_service import GmailInboundAutoSyncService
from app.services.gmail_inbound_sync_service import GmailInboundSyncService
from app.services.followup_policy_service import FOLLOWUP_ELIGIBLE_STATUSES, FollowUpPolicyService
from app.services.runtime_settings_service import get_runtime_bool_setting
from app.services.uber_connector_service import UberConnectorError, UberConnectorService

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
    f"{GITHUB_OIDC_REPOSITORY}/.github/workflows/tennet-uber-worker.yml@refs/heads/main",
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
                # Reserve Gmail per-user query quota for verified follow-up sends.
                # Reading stays continuous, but each pass is deliberately bounded.
                "gmail_watched_threads_batch_per_cycle": 20,
                "gmail_watched_threads_read_batch_per_cycle": 20,
                "gmail_starred_page_size": 100,
                "gmail_inbound_auto_sync_run_workspace_machine": False,
            }
        )
    result = GmailInboundAutoSyncService(
        provider=GmailEmailProvider(trusted_runtime=runtime_enabled),
        settings=settings,
    ).sync_due_accounts(db)
    db.commit()
    logger.info(
        "TENNET_GMAIL_SYNC status=%s checked=%s synced=%s messages=%s sent=%s failed=%s errors=%s",
        result.status,
        result.accounts_checked,
        result.accounts_synced,
        result.synced_messages,
        result.autopilot_sent_count,
        result.autopilot_failed_count,
        len(result.errors),
    )
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

    # Drain newest Uber history first. This feeds currently actionable
    # cancellations/refusals into TENNET quickly while still walking all the
    # way back to 2026-01-01 over subsequent cycles.
    day = today
    while day >= HISTORICAL_BACKFILL_START:
        day_key = day.isoformat()
        for account in accounts:
            if day_key not in completed_by_account[account.id]:
                return account, day
        day -= timedelta(days=1)
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
    # Restrict historical reads to Uber traffic. Fetching the entire mailbox
    # consumed Gmail "Total Query Cost" without helping recovery throughput.
    # 500 relevant Uber messages per account/day is a deliberately hard batch
    # ceiling; normal volumes are far below it.
    query = (
        f"after:{day.strftime('%Y/%m/%d')} "
        f"before:{next_day.strftime('%Y/%m/%d')} "
        "{from:uber.com to:restaurantsfrance@uber.com}"
    )
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
            full_history=False,
            include_starred_discovery=False,
        )
    except EmailProviderError as exc:
        db.rollback()
        # Keep precise provider failure metadata visible even if the
        # GitHub worker only reports the HTTP status to Vercel.
        logger.warning(
            "TENNET_GMAIL_BACKFILL_FAILED provider_status=%s provider_error=%s",
            exc.status_code,
            str(exc.message).replace("\n", " ")[:500],
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        db.rollback()
        safe_error = str(exc).replace("\n", " ").strip()
        if "password=" in safe_error.casefold():
            safe_error = "database_or_provider_error"
        logger.warning(
            "TENNET_GMAIL_BACKFILL_FAILED exception_type=%s summary=%s",
            type(exc).__name__,
            safe_error[:500],
        )
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
    logger.info(
        "TENNET_GMAIL_BACKFILL status=%s imported=%s linked=%s applied=%s errors=%s",
        result.status,
        result.synced_messages,
        result.linked_messages,
        result.applied_reviews,
        len(result.errors),
    )
    return payload



def _autopilot_blocker_summary(result) -> list[dict[str, object]]:
    if result is None:
        return []
    counts = Counter(
        action.skipped_reason
        for action in result.actions
        if action.status == "skipped" and action.skipped_reason
    )
    return [
        {"reason": reason, "count": count}
        for reason, count in counts.most_common(20)
    ]


def _followup_queue_diagnostics(
    db: Session,
    *,
    scan_limit: int = 50,
) -> dict[str, object]:
    """Explain why due follow-up tasks are not reaching AutoPilot.

    This is read-only diagnostic metadata for the trusted runtime worker.  It
    deliberately contains counts/reasons only: no order numbers, customer data,
    email addresses, message bodies or provider identifiers.
    """
    tasks = list(
        db.scalars(
            select(FollowUpTask)
            .join(ClaimOrder, FollowUpTask.order_id == ClaimOrder.id)
            .join(Restaurant, ClaimOrder.restaurant_id == Restaurant.id)
            .where(
                FollowUpTask.task_type.in_(tuple(FOLLOWUP_ACTION_BY_TASK.keys())),
                FollowUpTask.status.in_(("pending", "draft_created", "provider_draft_created")),
                FollowUpTask.due_at <= utc_now(),
            )
            .order_by(FollowUpTask.due_at, FollowUpTask.id)
            .limit(scan_limit)
        ).all()
    )

    blockers: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for task in tasks:
        status_counts[task.status] += 1
        restaurant = task.order.restaurant
        if not restaurant.active:
            reason = "restaurant_inactive"
        elif not restaurant.autopilot_enabled:
            reason = "restaurant_autopilot_disabled"
        else:
            reason = followup_skip_reason(db, task) or "eligible"
        blockers[reason] += 1

    return {
        "due_scanned": len(tasks),
        "scan_limit": scan_limit,
        "possibly_truncated": len(tasks) >= scan_limit,
        "status_counts": dict(status_counts),
        "blockers": [
            {"reason": reason, "count": count}
            for reason, count in blockers.most_common(20)
        ],
        "cooldown_hours": get_settings().autopilot_cooldown_hours,
        "max_followups_per_order": get_settings().max_followups_per_order,
    }


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

    # Rebuild any missing due follow-up tasks before scanning. This is
    # idempotent: FollowUpPolicyService will not duplicate an existing task.
    # It lets historical Gmail recovery feed the live sender immediately.
    recalculate = FollowUpPolicyService().recalculate(
        db,
        owner,
        select(ClaimOrder)
        .where(ClaimOrder.status.in_(FOLLOWUP_ELIGIBLE_STATUSES))
        .order_by(ClaimOrder.id),
        dry_run=False,
    )

    provider = GmailEmailProvider(trusted_runtime=True)
    repair = repair_followup_queue(
        db,
        owner,
        provider,
        max_items=500,
        max_remote_thread_repairs=4,
    )

    initial_claim_result = None
    followup_result = None
    appeal_result = None
    refund_result = None
    lane_order = ["initial_claims", "followups", "appeals", "refunds"]
    lane_offset = int(time.time() // 173) % len(lane_order)
    lane_order = lane_order[lane_offset:] + lane_order[:lane_offset]

    try:
        for lane in lane_order:
            if lane == "initial_claims":
                initial_claim_result = run_autopilot(
                    db,
                    owner,
                    mode="initial_claims",
                    restaurant_id=None,
                    dry_run=False,
                    provider=provider,
                    max_candidates=100,
                    trusted_runtime_initial_claims=True,
                )
            elif lane == "followups":
                followup_result = run_autopilot(
                    db,
                    owner,
                    mode="followups",
                    restaurant_id=None,
                    dry_run=False,
                    provider=provider,
                    max_candidates=100,
                    trusted_runtime_followups=True,
                )
            elif lane == "appeals":
                appeal_result = run_autopilot(
                    db,
                    owner,
                    mode="appeals",
                    restaurant_id=None,
                    dry_run=False,
                    provider=provider,
                    max_candidates=100,
                    trusted_runtime_appeals=True,
                )
            else:
                refund_result = run_customer_refund_autopilot(
                    db,
                    owner,
                    provider,
                    max_candidates=100,
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
                "lane_order": lane_order,
            }
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    initial_claim_payload = {
        "status": initial_claim_result.run.status if initial_claim_result is not None else "not_run",
        "run_id": initial_claim_result.run.id if initial_claim_result is not None else None,
        "total_candidates": initial_claim_result.run.total_candidates if initial_claim_result is not None else 0,
        "sent_count": initial_claim_result.run.sent_count if initial_claim_result is not None else 0,
        "skipped_count": initial_claim_result.run.skipped_count if initial_claim_result is not None else 0,
        "failed_count": initial_claim_result.run.failed_count if initial_claim_result is not None else 0,
        "error_message": initial_claim_result.run.error_message if initial_claim_result is not None else None,
    }
    followup_payload = {
        "status": followup_result.run.status if followup_result is not None else "not_run",
        "run_id": followup_result.run.id if followup_result is not None else None,
        "total_candidates": followup_result.run.total_candidates if followup_result is not None else 0,
        "sent_count": followup_result.run.sent_count if followup_result is not None else 0,
        "skipped_count": followup_result.run.skipped_count if followup_result is not None else 0,
        "failed_count": followup_result.run.failed_count if followup_result is not None else 0,
        "error_message": followup_result.run.error_message if followup_result is not None else None,
    }
    appeal_payload = {
        "status": appeal_result.run.status if appeal_result is not None else "not_run",
        "run_id": appeal_result.run.id if appeal_result is not None else None,
        "total_candidates": appeal_result.run.total_candidates if appeal_result is not None else 0,
        "sent_count": appeal_result.run.sent_count if appeal_result is not None else 0,
        "skipped_count": appeal_result.run.skipped_count if appeal_result is not None else 0,
        "failed_count": appeal_result.run.failed_count if appeal_result is not None else 0,
        "error_message": appeal_result.run.error_message if appeal_result is not None else None,
    }
    refund_payload = asdict(refund_result) if refund_result is not None else {
        "candidates": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "repaired_count": 0,
        "errors": (),
    }

    total_candidates = (
        int(initial_claim_payload["total_candidates"])
        + int(followup_payload["total_candidates"])
        + int(appeal_payload["total_candidates"])
        + int(refund_payload["candidates"])
    )
    sent_count = (
        int(initial_claim_payload["sent_count"])
        + int(followup_payload["sent_count"])
        + int(appeal_payload["sent_count"])
        + int(refund_payload["sent_count"])
    )
    skipped_count = (
        int(initial_claim_payload["skipped_count"])
        + int(followup_payload["skipped_count"])
        + int(appeal_payload["skipped_count"])
        + int(refund_payload["skipped_count"])
    )
    failed_count = (
        int(initial_claim_payload["failed_count"])
        + int(followup_payload["failed_count"])
        + int(appeal_payload["failed_count"])
        + int(refund_payload["failed_count"])
    )
    error_message = (
        initial_claim_payload["error_message"]
        or followup_payload["error_message"]
        or appeal_payload["error_message"]
        or ("; ".join(refund_payload["errors"][:5]) if refund_payload["errors"] else None)
    )

    followup_queue = (
        _followup_queue_diagnostics(db)
        if int(followup_payload["total_candidates"]) == 0
        else {"status": "candidates_present"}
    )

    payload = {
        "status": "failed" if failed_count else "completed",
        "run_id": initial_claim_payload["run_id"] or followup_payload["run_id"] or appeal_payload["run_id"],
        "total_candidates": total_candidates,
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "error_message": error_message,
        "lane_order": lane_order,
        "initial_claims": initial_claim_payload,
        "followups": followup_payload,
        "followup_blockers": _autopilot_blocker_summary(followup_result),
        "followup_queue": followup_queue,
        "appeals": appeal_payload,
        "appeal_blockers": _autopilot_blocker_summary(appeal_result),
        "customer_refunds": refund_payload,
        "followup_recalculate": {
            "created_tasks": recalculate.created_tasks,
            "skipped_orders": recalculate.skipped_orders,
            "manual_review_orders": recalculate.manual_review_orders,
            "errors": recalculate.errors[:20],
        },
        "self_heal": asdict(repair),
    }
    db.commit()
    logger.info(
        "TENNET_FOLLOWUP_WORKER candidates=%s sent=%s skipped=%s failed=%s tasks_created=%s blockers=%s",
        total_candidates,
        sent_count,
        skipped_count,
        failed_count,
        recalculate.created_tasks,
        json.dumps({
            "followups": payload["followup_blockers"][:8],
            "appeals": payload["appeal_blockers"][:8],
            "queue": payload["followup_queue"],
        }, default=str)[:1800],
    )
    return payload




@router.api_route("/uber-worker", methods=["GET", "POST"])
def run_uber_worker(
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _require_runtime_authorization(authorization)
    try:
        result = UberConnectorService().poll_cancellations(db)
    except UberConnectorError as exc:
        if exc.status_code in {409, 502}:
            return {
                "status": "blocked",
                "stores_checked": 0,
                "cancellations_seen": 0,
                "snapshots_created": 0,
                "snapshots_updated": 0,
                "error_message": exc.message,
            }
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {
        "status": "completed",
        "stores_checked": result.stores_checked,
        "cancellations_seen": result.cancellations_seen,
        "snapshots_created": result.snapshots_created,
        "snapshots_updated": result.snapshots_updated,
        "errors": list(result.errors),
    }


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
