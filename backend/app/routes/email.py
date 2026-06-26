import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.auth import (
    can_access_restaurant,
    ensure_can_access_order,
    get_accessible_restaurant_ids,
    get_current_user,
    require_owner,
    require_owner_or_manager,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    ClaimOrder,
    AuditLog,
    AutopilotAction,
    AutopilotRun,
    EmailAccount,
    EmailAccountRestaurantMapping,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    GmailSyncState,
    GmailResponseAnalysis,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.schemas.domain import (
    EmailProviderDraftRead,
    EmailAccountRead,
    EmailThreadRead,
    GmailConnectionStatus,
    GmailDraftCreate,
    GmailDraftSendRequest,
    GmailDraftSendResponse,
    GmailInboundStatusResponse,
    GmailInboundSyncRequest,
    GmailInboundSyncResponse,
    GmailOAuthStartResponse,
    GmailRelanceActionItem,
    GmailRelanceDashboardResponse,
    GmailRelanceMessageItem,
    GmailRelanceOrderSummary,
    GmailRelanceSentItem,
    GmailRelanceSummary,
    GmailRestaurantMappingRead,
    GmailRestaurantMappingUpdate,
    GmailWarRoomResponse,
    GmailWorkerBlockerSummary,
    GmailResponseAnalysisRead,
    GmailResponseAnalyzeRequest,
    GmailResponseAnalyzeResponse,
    GmailWatchedThreadItem,
    GmailWatchedThreadSummary,
    GmailWatchedWorkItem,
    GmailWorkerCycleSummary,
    InboundEmailMessageRead,
    InboundManualLinkRequest,
    InboundMessagesResponse,
    OrderEmailMessagesResponse,
    ResendSendRequest,
)
from app.services.audit import add_audit_log
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.followup_policy_service import complete_task_for_sent_provider_draft
from app.services.gmail_email_provider import GmailEmailProvider
from app.services.gmail_inbound_sync_service import (
    GMAIL_STARRED_URGENT_QUERIES,
    GmailInboundSyncResult,
    GmailInboundSyncService,
)
from app.services.gmail_quota import parse_gmail_retry_after_from_errors, seconds_until_gmail_retry
from app.services.gmail_response_intelligence_service import GmailResponseIntelligenceService
from app.services.gmail_watched_thread_monitor_service import GmailWatchedThreadMonitorService
from app.services.resend_email_provider import ResendEmailProvider
from app.services.response_review_service import ResponseReviewError

router = APIRouter(tags=["email"])
FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def get_gmail_provider() -> EmailProvider:
    return GmailEmailProvider()


def get_resend_provider() -> ResendEmailProvider:
    return ResendEmailProvider()


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _as_error_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item)[:240] for item in value if item]
    if isinstance(value, str) and value:
        return [value[:240]]
    return []


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _last_gmail_auto_sync_cycle(db: Session) -> GmailWorkerCycleSummary | None:
    audit = db.scalar(
        select(AuditLog)
        .where(AuditLog.entity_type == "gmail_auto_sync")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    if audit is None:
        return None

    payload: dict[str, object] = {}
    if audit.new_value:
        try:
            decoded = json.loads(audit.new_value)
            if isinstance(decoded, dict):
                payload = decoded
        except json.JSONDecodeError:
            payload = {}

    return GmailWorkerCycleSummary(
        created_at=audit.created_at,
        accounts_checked=_as_int(payload.get("accounts_checked")),
        accounts_synced=_as_int(payload.get("accounts_synced")),
        accounts_skipped=_as_int(payload.get("accounts_skipped")),
        synced_messages=_as_int(payload.get("synced_messages")),
        applied_reviews=_as_int(payload.get("applied_reviews")),
        negative_responses_detected=_as_int(payload.get("negative_responses_detected")),
        watched_threads_seen=_as_int(payload.get("watched_threads_seen")),
        watched_threads_created=_as_int(payload.get("watched_threads_created")),
        watched_thread_new_messages=_as_int(payload.get("watched_thread_new_messages")),
        watched_thread_processed_messages=_as_int(payload.get("watched_thread_processed_messages")),
        watched_thread_positive_responses=_as_int(payload.get("watched_thread_positive_responses")),
        watched_thread_refused_responses=_as_int(payload.get("watched_thread_refused_responses")),
        watched_thread_evidence_requests=_as_int(payload.get("watched_thread_evidence_requests")),
        watched_thread_manual_reviews=_as_int(payload.get("watched_thread_manual_reviews")),
        autopilot_sent_count=_as_int(payload.get("autopilot_sent_count")),
        autopilot_skipped_count=_as_int(payload.get("autopilot_skipped_count")),
        autopilot_failed_count=_as_int(payload.get("autopilot_failed_count")),
        workspace_machine_runs=_as_int(payload.get("workspace_machine_runs")),
        errors=_as_error_list(payload.get("errors")),
    )


def _last_autopilot_blockers(db: Session, current_user: User) -> list[GmailWorkerBlockerSummary]:
    latest_run = db.scalar(
        select(AutopilotRun)
        .where(AutopilotRun.mode != "emergency_stop")
        .order_by(AutopilotRun.created_at.desc(), AutopilotRun.id.desc())
        .limit(1)
    )
    if latest_run is None:
        return []

    statement = (
        select(
            AutopilotAction.action_type,
            func.coalesce(AutopilotAction.skipped_reason, AutopilotAction.reason).label("skipped_reason"),
            func.count(AutopilotAction.id).label("count"),
        )
        .where(
            AutopilotAction.run_id == latest_run.id,
            AutopilotAction.status == "skipped",
        )
        .group_by(AutopilotAction.action_type, func.coalesce(AutopilotAction.skipped_reason, AutopilotAction.reason))
        .order_by(func.count(AutopilotAction.id).desc(), AutopilotAction.action_type)
        .limit(8)
    )
    accessible_ids = get_accessible_restaurant_ids(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            return []
        statement = statement.where(AutopilotAction.restaurant_id.in_(accessible_ids))

    return [
        GmailWorkerBlockerSummary(
            action_type=str(action_type),
            skipped_reason=str(skipped_reason),
            count=int(count),
        )
        for action_type, skipped_reason, count in db.execute(statement).all()
    ]


@router.get("/v1/email/gmail/status", response_model=GmailConnectionStatus)
def gmail_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailConnectionStatus:
    status_payload = provider.get_connection_status(db, current_user).__dict__
    status_payload["accounts"] = [
        EmailAccountRead.model_validate(account)
        for account in get_connected_gmail_accounts(db, current_user)
    ]
    return GmailConnectionStatus.model_validate(status_payload)


@router.get("/v1/email/gmail/accounts", response_model=list[EmailAccountRead])
def list_gmail_accounts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[EmailAccountRead]:
    return [EmailAccountRead.model_validate(account) for account in get_connected_gmail_accounts(db, current_user)]


@router.get("/v1/email/gmail/restaurant-mappings", response_model=list[GmailRestaurantMappingRead])
def list_gmail_restaurant_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> list[GmailRestaurantMappingRead]:
    restaurants = get_visible_restaurants_for_email_settings(db, current_user)
    rows: list[GmailRestaurantMappingRead] = []
    for restaurant in restaurants:
        mapping = restaurant.email_account_mapping
        account = mapping.email_account if mapping else None
        if account is not None and account.disconnected_at is not None:
            account = None
        rows.append(
            GmailRestaurantMappingRead(
                id=mapping.id if mapping else None,
                restaurant_id=restaurant.id,
                restaurant_name=restaurant.name,
                email_account_id=account.id if account else None,
                email_address=account.email_address if account else None,
                created_at=mapping.created_at if mapping else None,
                updated_at=mapping.updated_at if mapping else None,
            )
        )
    return rows


@router.put("/v1/email/gmail/restaurant-mappings/{restaurant_id}", response_model=GmailRestaurantMappingRead)
def update_gmail_restaurant_mapping(
    restaurant_id: int,
    payload: GmailRestaurantMappingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
) -> GmailRestaurantMappingRead:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    existing_mapping = db.scalar(
        select(EmailAccountRestaurantMapping).where(EmailAccountRestaurantMapping.restaurant_id == restaurant_id)
    )
    if payload.email_account_id is None:
        if existing_mapping is not None:
            old_value = {
                "restaurant_id": restaurant_id,
                "email_account_id": existing_mapping.email_account_id,
            }
            db.delete(existing_mapping)
            add_audit_log(
                db,
                entity_type="email_account_restaurant_mapping",
                entity_id=restaurant_id,
                action="gmail_restaurant_mapping.deleted",
                user_id=current_user.id,
                old_value=old_value,
            )
            db.commit()
        return GmailRestaurantMappingRead(
            id=None,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            email_account_id=None,
            email_address=None,
        )

    account = db.get(EmailAccount, payload.email_account_id)
    if (
        account is None
        or account.user_id != current_user.id
        or account.provider != "gmail"
        or account.disconnected_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connected Gmail account not found")

    if existing_mapping is None:
        existing_mapping = EmailAccountRestaurantMapping(
            restaurant_id=restaurant_id,
            email_account_id=account.id,
            created_by_user_id=current_user.id,
        )
        db.add(existing_mapping)
        action = "gmail_restaurant_mapping.created"
        old_value = None
    else:
        old_value = {
            "restaurant_id": restaurant_id,
            "email_account_id": existing_mapping.email_account_id,
        }
        existing_mapping.email_account_id = account.id
        action = "gmail_restaurant_mapping.updated"

    db.flush()
    add_audit_log(
        db,
        entity_type="email_account_restaurant_mapping",
        entity_id=existing_mapping.id,
        action=action,
        user_id=current_user.id,
        old_value=old_value,
        new_value={"restaurant_id": restaurant_id, "email_account_id": account.id, "email_address": account.email_address},
    )
    db.commit()
    db.refresh(existing_mapping)
    return GmailRestaurantMappingRead(
        id=existing_mapping.id,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        email_account_id=account.id,
        email_address=account.email_address,
        created_at=existing_mapping.created_at,
        updated_at=existing_mapping.updated_at,
    )


@router.get("/v1/email/resend/status", response_model=GmailConnectionStatus, response_model_exclude={"accounts"})
def resend_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: ResendEmailProvider = Depends(get_resend_provider),
) -> GmailConnectionStatus:
    return GmailConnectionStatus.model_validate(provider.get_connection_status(db, current_user).__dict__)


@router.get("/v1/email/gmail/oauth/start", response_model=GmailOAuthStartResponse)
def start_gmail_oauth(
    current_user: User = Depends(get_current_user),
    provider: GmailEmailProvider = Depends(get_gmail_provider),
) -> GmailOAuthStartResponse:
    try:
        authorization_url = provider.build_authorization_url(current_user)
    except EmailProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return GmailOAuthStartResponse(authorization_url=authorization_url)


@router.get("/v1/email/gmail/oauth/callback", response_class=HTMLResponse)
def gmail_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
    provider: GmailEmailProvider = Depends(get_gmail_provider),
) -> HTMLResponse:
    try:
        account = provider.handle_oauth_callback(db, state, code)
    except EmailProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    add_audit_log(
        db,
        entity_type="email_account",
        entity_id=account.id,
        action="gmail_account.connected",
        user_id=account.user_id,
        new_value={"provider": account.provider, "email_address": account.email_address},
    )
    db.commit()
    return HTMLResponse(
        "<html><body><h1>Gmail connected</h1><p>You can close this window and return to TENNET.</p></body></html>"
    )


@router.post("/v1/email/gmail/disconnect")
def disconnect_gmail(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> dict[str, bool]:
    try:
        provider.disconnect(db, current_user)
    except EmailProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    add_audit_log(
        db,
        entity_type="email_account",
        entity_id=current_user.id,
        action="gmail_account.disconnected",
        user_id=current_user.id,
        new_value={"provider": "gmail"},
    )
    db.commit()
    return {"disconnected": True}


@router.post("/v1/drafts/{draft_id}/gmail-draft", response_model=EmailProviderDraftRead)
def create_gmail_draft(
    draft_id: int,
    payload: GmailDraftCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> EmailProviderDraftRead:
    email_draft = db.get(EmailDraft, draft_id)
    if email_draft is None:
        raise HTTPException(status_code=404, detail="Email draft not found")
    ensure_can_access_order(db, current_user, email_draft.order)

    to_email = (payload.to_email or get_settings().default_uber_eats_support_email).strip()
    if not to_email:
        raise HTTPException(status_code=400, detail="Recipient email is required")

    try:
        provider_draft = provider.create_draft(
            db,
            current_user,
            email_draft,
            to_email=to_email,
            include_evidence=payload.include_evidence,
        )
    except EmailProviderError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    add_audit_log(
        db,
        entity_type="email_provider_draft",
        entity_id=provider_draft.id,
        action="gmail_draft.created",
        user_id=current_user.id,
        new_value={
            "email_draft_id": email_draft.id,
            "order_id": email_draft.order_id,
            "provider": provider_draft.provider,
            "provider_draft_id": provider_draft.provider_draft_id,
            "to_email": provider_draft.to_email,
            "status": provider_draft.status,
        },
    )
    db.commit()
    db.refresh(provider_draft)
    return EmailProviderDraftRead.model_validate(provider_draft)


@router.post(
    "/v1/email/gmail/provider-drafts/{provider_draft_id}/send",
    response_model=GmailDraftSendResponse,
)
def send_gmail_provider_draft(
    provider_draft_id: str,
    payload: GmailDraftSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailDraftSendResponse:
    if payload.confirm_send is not True:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm_send must be true")

    provider_draft = db.scalar(
        select(EmailProviderDraft)
        .where(
            EmailProviderDraft.provider == "gmail",
            EmailProviderDraft.provider_draft_id == provider_draft_id,
        )
        .order_by(EmailProviderDraft.id.desc())
    )
    if provider_draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gmail provider draft not found")

    email_draft = provider_draft.email_draft
    order = email_draft.order
    ensure_can_access_order(db, current_user, order)

    if provider_draft.status == "sent":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gmail draft has already been sent")
    if provider_draft.status == "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gmail draft send has failed; retry is not enabled")
    if provider_draft.status != "provider_draft_created":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gmail draft is not ready to send")
    if order.status in FINAL_ORDER_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Final order status cannot be sent")

    connection_status = provider.get_connection_status(db, current_user)
    if not connection_status.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email provider is disabled")
    if not connection_status.connected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gmail account is not connected")

    old_status = provider_draft.status
    provider_draft.status = "send_requested"
    provider_draft.updated_at = utc_now()
    db.flush()

    try:
        send_result = provider.send_draft(db, current_user, provider_draft)
    except EmailProviderError as exc:
        provider_draft.status = "failed"
        provider_draft.last_error = exc.message
        provider_draft.updated_at = utc_now()
        add_audit_log(
            db,
            entity_type="email_provider_draft",
            entity_id=provider_draft.id,
            action="send_gmail_draft_failed",
            user_id=current_user.id,
            old_value={"status": old_status},
            new_value={"status": "failed", "error": exc.message},
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    provider_draft.status = "sent"
    provider_draft.sent_at = send_result.sent_at
    provider_draft.sent_by_user_id = current_user.id
    provider_draft.provider_message_id = send_result.provider_message_id
    provider_draft.provider_thread_id = send_result.provider_thread_id or provider_draft.provider_thread_id
    provider_draft.last_error = None
    provider_draft.updated_at = utc_now()

    order.status = "sent"
    if order.first_email_sent_at is None:
        order.first_email_sent_at = provider_draft.sent_at
    order.updated_at = utc_now()
    db.add(
        EmailThread(
            order_id=order.id,
            provider="gmail",
            thread_id=provider_draft.provider_thread_id,
            message_id=provider_draft.provider_message_id,
            direction="outbound",
            subject=provider_draft.subject,
            body=email_draft.body,
            sent_at=provider_draft.sent_at,
        )
    )
    add_audit_log(
        db,
        entity_type="email_provider_draft",
        entity_id=provider_draft.id,
        action="send_gmail_draft",
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={
            "status": provider_draft.status,
            "provider_message_id": provider_draft.provider_message_id,
            "provider_thread_id": provider_draft.provider_thread_id,
            "order_id": order.id,
        },
    )
    complete_task_for_sent_provider_draft(db, current_user, provider_draft)
    db.commit()
    db.refresh(provider_draft)

    return GmailDraftSendResponse(
        provider_draft_id=provider_draft.provider_draft_id or provider_draft_id,
        status=provider_draft.status,
        provider_message_id=provider_draft.provider_message_id,
        provider_thread_id=provider_draft.provider_thread_id,
        sent_at=provider_draft.sent_at,
    )


@router.post("/v1/drafts/{draft_id}/resend-send", response_model=EmailProviderDraftRead)
def send_resend_email_draft(
    draft_id: int,
    payload: ResendSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: ResendEmailProvider = Depends(get_resend_provider),
) -> EmailProviderDraftRead:
    if payload.confirm_send is not True:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="confirm_send must be true")

    email_draft = db.get(EmailDraft, draft_id)
    if email_draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email draft not found")
    order = email_draft.order
    ensure_can_access_order(db, current_user, order)
    if order.status in FINAL_ORDER_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Final order status cannot be sent")

    to_email = (payload.to_email or get_settings().default_uber_eats_support_email).strip()
    if not to_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Recipient email is required")

    try:
        provider_draft = provider.send_email(
            db,
            current_user,
            email_draft,
            to_email=to_email,
            include_evidence=payload.include_evidence,
        )
    except EmailProviderError as exc:
        add_audit_log(
            db,
            entity_type="email_draft",
            entity_id=email_draft.id,
            action="send_resend_email_failed",
            user_id=current_user.id,
            new_value={"order_id": order.id, "error": exc.message},
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order.status = "sent"
    if order.first_email_sent_at is None:
        order.first_email_sent_at = provider_draft.sent_at
    order.updated_at = utc_now()
    db.add(
        EmailThread(
            order_id=order.id,
            provider="resend",
            thread_id=provider_draft.provider_thread_id,
            message_id=provider_draft.provider_message_id,
            direction="outbound",
            subject=provider_draft.subject,
            body=email_draft.body,
            sent_at=provider_draft.sent_at,
        )
    )
    add_audit_log(
        db,
        entity_type="email_provider_draft",
        entity_id=provider_draft.id,
        action="send_resend_email",
        user_id=current_user.id,
        new_value={
            "status": provider_draft.status,
            "provider_message_id": provider_draft.provider_message_id,
            "order_id": order.id,
        },
    )
    complete_task_for_sent_provider_draft(db, current_user, provider_draft)
    db.commit()
    db.refresh(provider_draft)
    return EmailProviderDraftRead.model_validate(provider_draft)


@router.get("/v1/email/gmail/inbound/status", response_model=GmailInboundStatusResponse)
def gmail_inbound_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailInboundStatusResponse:
    settings = get_settings()
    connection_status = provider.get_connection_status(db, current_user)
    connected_accounts = get_connected_gmail_accounts(db, current_user)
    account_ids = [account.id for account in connected_accounts]
    sync_states = (
        list(db.scalars(select(GmailSyncState).where(GmailSyncState.email_account_id.in_(account_ids))).all())
        if account_ids
        else []
    )
    latest_sync_state = max(
        sync_states,
        key=lambda item: item.last_sync_at or item.last_success_at or item.updated_at,
        default=None,
    )
    last_cycle = _last_gmail_auto_sync_cycle(db)
    latest_sync_at = _as_aware_utc(max((state.last_sync_at for state in sync_states if state.last_sync_at), default=None))
    latest_success_at = _as_aware_utc(max((state.last_success_at for state in sync_states if state.last_success_at), default=None))
    base_time = latest_success_at or latest_sync_at or _as_aware_utc(last_cycle.created_at if last_cycle else None)
    interval_seconds = settings.gmail_inbound_auto_sync_interval_seconds
    continuous_enabled = settings.gmail_inbound_auto_sync_continuous_enabled
    next_sync_at = (
        base_time + timedelta(seconds=interval_seconds)
        if base_time and settings.gmail_inbound_auto_sync_enabled and not continuous_enabled
        else None
    )
    now = utc_now()
    seconds_until_next_sync = 0 if settings.gmail_inbound_auto_sync_enabled and continuous_enabled else None
    if next_sync_at is not None:
        seconds_until_next_sync = max(0, int((next_sync_at - now).total_seconds()))

    has_cycle_errors = bool(last_cycle and last_cycle.errors)
    has_sync_errors = any(state.last_error for state in sync_states)
    quota_retry_after = parse_gmail_retry_after_from_errors(
        [state.last_error or "" for state in sync_states],
        now=now,
    )
    if last_cycle is not None:
        cycle_retry_after = parse_gmail_retry_after_from_errors(last_cycle.errors, now=now)
        if cycle_retry_after is not None and (quota_retry_after is None or cycle_retry_after > quota_retry_after):
            quota_retry_after = cycle_retry_after
    quota_seconds_until_retry = seconds_until_gmail_retry(quota_retry_after, now=now)
    quota_blocked = quota_seconds_until_retry is not None and quota_seconds_until_retry > 0
    processed_last_24h = (
        int(
            db.scalar(
                select(func.count(GmailStarredWorkItem.id)).where(
                    GmailStarredWorkItem.email_account_id.in_(account_ids),
                    GmailStarredWorkItem.processed_at >= now - timedelta(hours=24),
                    GmailStarredWorkItem.status.in_(
                        ["processed", "positive", "refused", "evidence_needed", "manual_review"]
                    ),
                )
            )
            or 0
        )
        if account_ids
        else 0
    )
    overdue = (
        settings.gmail_inbound_auto_sync_enabled
        and (
            (
                next_sync_at is not None
                and now > next_sync_at + timedelta(seconds=interval_seconds * 2)
            )
            or (
                continuous_enabled
                and base_time is not None
                and now > base_time + timedelta(seconds=600)
            )
        )
    )
    if not settings.email_provider_enabled or not settings.gmail_inbound_sync_enabled:
        worker_state = "disabled"
        worker_message = "Lecture Gmail desactivee sur cet environnement."
    elif not connection_status.connected or not connected_accounts:
        worker_state = "attention"
        worker_message = "Aucun compte Gmail connecte."
    elif not settings.gmail_inbound_auto_sync_enabled:
        worker_state = "attention"
        worker_message = "Sync Gmail automatique desactivee."
    elif quota_blocked:
        worker_state = "attention"
        worker_message = "Gmail demande une pause quota. TENNET reprend automatiquement."
    elif has_cycle_errors or has_sync_errors:
        worker_state = "attention"
        worker_message = "Dernier passage Gmail avec erreur a verifier."
    elif overdue:
        worker_state = "attention"
        worker_message = "Le worker Gmail semble en retard."
    else:
        worker_state = "active"
        worker_message = "TENNET surveille Gmail automatiquement."

    return GmailInboundStatusResponse(
        enabled=settings.email_provider_enabled and settings.gmail_inbound_sync_enabled,
        connected=connection_status.connected,
        auto_sync_enabled=settings.gmail_inbound_auto_sync_enabled,
        auto_sync_continuous_enabled=continuous_enabled,
        auto_sync_interval_seconds=(
            None
            if settings.gmail_inbound_auto_sync_enabled and continuous_enabled
            else settings.gmail_inbound_auto_sync_interval_seconds
        ),
        auto_sync_run_autopilot=settings.gmail_inbound_auto_sync_run_autopilot,
        auto_sync_run_workspace_machine=settings.gmail_inbound_auto_sync_run_workspace_machine,
        autopilot_enabled=settings.autopilot_enabled,
        autopilot_initial_claims_enabled=settings.autopilot_initial_claims_enabled,
        autopilot_followups_enabled=settings.autopilot_followups_enabled,
        autopilot_appeals_enabled=settings.autopilot_appeals_enabled,
        autopilot_require_complete_restaurant_signature=settings.autopilot_require_complete_restaurant_signature,
        ai_gmail_analysis_enabled=settings.ai_gmail_analysis_enabled,
        connected_accounts_count=len(connected_accounts),
        connected_account_emails=[
            account.email_address or f"Compte Gmail #{account.id}"
            for account in connected_accounts
        ],
        last_sync_at=latest_sync_at,
        last_success_at=latest_success_at,
        next_sync_at=next_sync_at,
        seconds_until_next_sync=seconds_until_next_sync,
        quota_blocked=quota_blocked,
        quota_retry_after=quota_retry_after,
        quota_seconds_until_retry=quota_seconds_until_retry,
        daily_processing_target=settings.gmail_daily_processing_target,
        processed_last_24h=processed_last_24h,
        worker_state=worker_state,
        worker_message=worker_message,
        last_cycle=last_cycle,
        status=latest_sync_state.status if latest_sync_state else None,
        last_error=next((state.last_error for state in sync_states if state.last_error), None),
        last_autopilot_blockers=_last_autopilot_blockers(db, current_user),
    )


def _labels_include_starred(labels: object) -> bool:
    if not isinstance(labels, list):
        return False
    return any(str(label).upper() == "STARRED" for label in labels)


GMAIL_RELANCE_DASHBOARD_STARRED_REFRESH_LIMIT = 120


def _refresh_starred_messages_for_relance_dashboard(
    db: Session,
    current_user: User,
    provider: EmailProvider,
    connected_accounts: list[EmailAccount],
    *,
    limit: int,
) -> None:
    """Lightweight Gmail refresh for the operator dashboard.

    The normal worker can take time to walk a large mailbox. The relance page
    still needs to show what Gmail currently has starred, so refresh a bounded
    starred Gmail slice without running a full mailbox scan from a GET request.
    """
    settings = get_settings()
    if not settings.email_provider_enabled or not settings.gmail_inbound_sync_enabled:
        return
    if not connected_accounts:
        return

    service = GmailInboundSyncService(provider)
    order_identifier_index = service.build_order_identifier_index(db, current_user)
    max_messages = min(max(limit, 10), GMAIL_RELANCE_DASHBOARD_STARRED_REFRESH_LIMIT)
    result = GmailInboundSyncResult(status="success")

    for account in connected_accounts:
        try:
            payloads = service.fetch_starred_payloads_for_queries(
                db,
                current_user,
                account,
                queries=GMAIL_STARRED_URGENT_QUERIES,
                fallback_max_messages=max_messages,
                use_full_history=False,
            )
        except EmailProviderError:
            continue

        for payload in payloads:
            if not payload.provider_message_id:
                continue
            existing_message = service.get_existing_message(db, account, payload.provider_message_id)
            if existing_message is not None:
                service.refresh_existing_message_from_payload(db, current_user, existing_message, payload)
                service.reprocess_existing_message(
                    db,
                    current_user,
                    account,
                    existing_message,
                    result,
                    apply_reviews=True,
                    payload=payload,
                )
                service.ensure_starred_linked_message_is_actionable(db, current_user, existing_message, result)
                continue

            inbound_message = service.create_inbound_message(
                db,
                current_user,
                account,
                payload,
                order_identifier_index=order_identifier_index,
            )
            result.synced_messages += 1
            service.reprocess_existing_message(
                db,
                current_user,
                account,
                inbound_message,
                result,
                apply_reviews=True,
                payload=payload,
            )
            service.ensure_starred_linked_message_is_actionable(db, current_user, inbound_message, result)

        GmailWatchedThreadMonitorService(provider, sync_service=service).discover_from_starred_messages(
            db,
            current_user,
            account,
            use_full_history=False,
            max_messages=max_messages,
        )

    db.commit()


def _short_text(value: str | None, limit: int = 260) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1].rstrip()}..."


def _gmail_relance_order_summary(order: ClaimOrder | None) -> GmailRelanceOrderSummary | None:
    if order is None:
        return None
    return GmailRelanceOrderSummary(
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        restaurant_name=order.restaurant.name if order.restaurant else None,
        uber_order_number=order.uber_order_number,
        customer_name=order.customer_name,
        order_date=order.order_date,
        order_amount=order.order_amount,
        currency=order.currency,
        status=order.status,
    )


def _accessible_restaurant_filter(db: Session, user: User) -> list[int] | None:
    accessible_ids = get_accessible_restaurant_ids(db, user)
    if accessible_ids is None:
        return None
    return list(accessible_ids)


def _gmail_relance_actions_query(db: Session, user: User):
    statement = (
        select(AutopilotAction)
        .options(
            selectinload(AutopilotAction.restaurant),
            selectinload(AutopilotAction.email_draft),
            selectinload(AutopilotAction.provider_draft),
        )
        .order_by(
            AutopilotAction.sent_at.desc().nullslast(),
            AutopilotAction.updated_at.desc(),
            AutopilotAction.id.desc(),
        )
    )
    accessible_ids = _accessible_restaurant_filter(db, user)
    if accessible_ids is not None:
        if not accessible_ids:
            return statement.where(AutopilotAction.id == -1)
        statement = statement.where(AutopilotAction.restaurant_id.in_(accessible_ids))
    return statement


def _gmail_relance_provider_drafts_query(db: Session, user: User):
    statement = (
        select(EmailProviderDraft)
        .join(EmailProviderDraft.email_draft)
        .join(EmailDraft.order)
        .options(
            selectinload(EmailProviderDraft.email_account),
            selectinload(EmailProviderDraft.email_draft)
            .selectinload(EmailDraft.order)
            .selectinload(ClaimOrder.restaurant),
        )
        .where(EmailProviderDraft.provider == "gmail")
        .order_by(
            EmailProviderDraft.sent_at.desc().nullslast(),
            EmailProviderDraft.updated_at.desc(),
            EmailProviderDraft.id.desc(),
        )
    )
    accessible_ids = _accessible_restaurant_filter(db, user)
    if accessible_ids is not None:
        if not accessible_ids:
            return statement.where(EmailProviderDraft.id == -1)
        statement = statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
    return statement


@router.get("/v1/email/gmail/relances", response_model=GmailRelanceDashboardResponse)
def gmail_relance_dashboard(
    limit: int = Query(default=80, ge=10, le=200),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailRelanceDashboardResponse:
    connected_accounts = get_connected_gmail_accounts(db, current_user)
    if refresh:
        _refresh_starred_messages_for_relance_dashboard(
            db,
            current_user,
            provider,
            connected_accounts,
            limit=limit,
        )
    worker_status = gmail_inbound_status(db=db, current_user=current_user, provider=provider)
    account_email_by_id = {account.id: account.email_address for account in connected_accounts}
    since_24h = utc_now() - timedelta(hours=24)

    labels_text = cast(InboundEmailMessage.provider_labels_json, String)
    starred_messages_base_statement = visible_inbound_messages_query(db, current_user).where(
        InboundEmailMessage.provider == "gmail",
        labels_text.ilike("%STARRED%"),
    )
    starred_total = int(
        db.scalar(starred_messages_base_statement.with_only_columns(func.count(InboundEmailMessage.id)).order_by(None))
        or 0
    )
    unlinked_starred_total = int(
        db.scalar(
            starred_messages_base_statement.where(InboundEmailMessage.order_id.is_(None))
            .with_only_columns(func.count(InboundEmailMessage.id))
            .order_by(None)
        )
        or 0
    )
    visible_messages_statement = (
        starred_messages_base_statement
        .options(
            selectinload(InboundEmailMessage.email_account),
            selectinload(InboundEmailMessage.response_analysis),
            selectinload(InboundEmailMessage.order).selectinload(ClaimOrder.restaurant),
        )
        .order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
        .limit(limit)
    )
    visible_messages = list(db.scalars(visible_messages_statement).all())
    latest_starred_messages = [message for message in visible_messages if _labels_include_starred(message.provider_labels_json)]

    message_items = [
        GmailRelanceMessageItem(
            id=message.id,
            email_account_id=message.email_account_id,
            account_email=message.email_account.email_address if message.email_account else account_email_by_id.get(message.email_account_id),
            provider_thread_id=message.provider_thread_id,
            provider_message_id=message.provider_message_id,
            subject=message.subject,
            from_email=message.from_email,
            to_email=message.to_email,
            snippet=_short_text(message.snippet or message.body_text),
            received_at=message.received_at,
            is_starred=True,
            match_status=message.match_status,
            match_reason=message.match_reason,
            review_status=message.review_status,
            order=_gmail_relance_order_summary(message.order),
            analysis_type=message.response_analysis.recommended_review_type if message.response_analysis else None,
            analysis_status=message.response_analysis.status if message.response_analysis else None,
            analysis_reason=message.response_analysis.reason if message.response_analysis else None,
            detected_amount=message.response_analysis.detected_amount if message.response_analysis else None,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )
        for message in latest_starred_messages
    ]

    sent_drafts = list(db.scalars(_gmail_relance_provider_drafts_query(db, current_user).limit(limit)).all())
    sent_items = [
        GmailRelanceSentItem(
            id=draft.id,
            email_account_id=draft.email_account_id,
            account_email=draft.email_account.email_address if draft.email_account else None,
            provider_thread_id=draft.provider_thread_id,
            provider_message_id=draft.provider_message_id,
            to_email=draft.to_email,
            subject=draft.subject,
            status=draft.status,
            sent_at=draft.sent_at,
            error_message=_short_text(draft.error_message, 180),
            last_error=_short_text(draft.last_error, 180),
            order=_gmail_relance_order_summary(draft.email_draft.order if draft.email_draft else None),
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
        for draft in sent_drafts
    ]

    actions = list(db.scalars(_gmail_relance_actions_query(db, current_user).limit(limit)).all())
    action_order_ids = [action.case_id for action in actions if action.case_type == "claim_order"]
    action_orders = (
        list(
            db.scalars(
                select(ClaimOrder)
                .options(selectinload(ClaimOrder.restaurant))
                .where(ClaimOrder.id.in_(action_order_ids))
            ).all()
        )
        if action_order_ids
        else []
    )
    action_orders_by_id = {order.id: order for order in action_orders}
    action_items = [
        GmailRelanceActionItem(
            id=action.id,
            run_id=action.run_id,
            case_type=action.case_type,
            case_id=action.case_id,
            restaurant_id=action.restaurant_id,
            restaurant_name=action.restaurant.name if action.restaurant else None,
            action_type=action.action_type,
            status=action.status,
            reason=action.reason,
            skipped_reason=_short_text(action.skipped_reason, 180),
            email_draft_id=action.email_draft_id,
            provider_draft_id=action.provider_draft_id,
            sent_at=action.sent_at,
            order=_gmail_relance_order_summary(action_orders_by_id.get(action.case_id)),
            created_at=action.created_at,
            updated_at=action.updated_at,
        )
        for action in actions
    ]

    sent_count_statement = (
        select(func.count(EmailProviderDraft.id))
        .join(EmailProviderDraft.email_draft)
        .join(EmailDraft.order)
        .where(
            EmailProviderDraft.provider == "gmail",
            EmailProviderDraft.status == "sent",
            EmailProviderDraft.sent_at >= since_24h,
        )
    )
    blocked_count_statement = select(func.count(AutopilotAction.id)).where(
        AutopilotAction.created_at >= since_24h,
        AutopilotAction.status.in_(["skipped", "failed", "manual_review"]),
    )
    payment_signal_statement = (
        select(func.count(GmailResponseAnalysis.id))
        .join(InboundEmailMessage)
        .where(
            GmailResponseAnalysis.created_at >= since_24h,
            GmailResponseAnalysis.recommended_review_type.in_(["accepted", "payment_to_verify", "payment_confirmed"]),
        )
    )

    accessible_ids = _accessible_restaurant_filter(db, current_user)
    if accessible_ids is not None:
        if not accessible_ids:
            sent_count_statement = sent_count_statement.where(EmailProviderDraft.id == -1)
            blocked_count_statement = blocked_count_statement.where(AutopilotAction.id == -1)
            payment_signal_statement = payment_signal_statement.where(InboundEmailMessage.id == -1)
        else:
            sent_count_statement = sent_count_statement.where(ClaimOrder.restaurant_id.in_(accessible_ids))
            blocked_count_statement = blocked_count_statement.where(AutopilotAction.restaurant_id.in_(accessible_ids))
            accessible_order_ids = select(ClaimOrder.id).where(ClaimOrder.restaurant_id.in_(accessible_ids))
            payment_signal_statement = payment_signal_statement.where(InboundEmailMessage.order_id.in_(accessible_order_ids))

    summary = GmailRelanceSummary(
        connected_accounts_count=len(connected_accounts),
        starred_threads_seen=starred_total,
        unlinked_starred_threads=unlinked_starred_total,
        sent_relances_last_24h=int(db.scalar(sent_count_statement) or 0),
        blocked_actions_last_24h=int(db.scalar(blocked_count_statement) or 0),
        payment_signals_last_24h=int(db.scalar(payment_signal_statement) or 0),
        latest_cycle_sent_count=worker_status.last_cycle.autopilot_sent_count if worker_status.last_cycle else 0,
        latest_cycle_skipped_count=worker_status.last_cycle.autopilot_skipped_count if worker_status.last_cycle else 0,
        latest_cycle_failed_count=worker_status.last_cycle.autopilot_failed_count if worker_status.last_cycle else 0,
    )

    return GmailRelanceDashboardResponse(
        updated_at=utc_now(),
        worker=worker_status,
        summary=summary,
        starred_threads=message_items,
        sent_relances=sent_items,
        recent_actions=action_items,
    )


@router.get("/v1/email/gmail/war-room", response_model=GmailWarRoomResponse)
def gmail_war_room(
    limit: int = Query(default=120, ge=10, le=500),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailWarRoomResponse:
    connected_accounts = get_connected_gmail_accounts(db, current_user)
    account_ids = [account.id for account in connected_accounts]
    account_email_by_id = {account.id: account.email_address for account in connected_accounts}
    if refresh and connected_accounts:
        settings = get_settings()
        sync_service = GmailInboundSyncService(provider)
        monitor = GmailWatchedThreadMonitorService(provider, settings=settings, sync_service=sync_service)
        refresh_batch_limit = min(
            limit,
            settings.gmail_watched_threads_batch_per_cycle,
            settings.gmail_watched_threads_max_per_cycle,
        )
        for account in connected_accounts:
            try:
                watched_result = monitor.process_account(
                    db,
                    current_user,
                    account,
                    max_threads=refresh_batch_limit,
                    discover_starred=True,
                    discover_full_history=False,
                    starred_discovery_max_messages=refresh_batch_limit,
                    process_new_messages=True,
                )
            except Exception as exc:  # noqa: BLE001 - one Gmail account must not break the live dashboard.
                add_audit_log(
                    db,
                    user_id=current_user.id,
                    action="gmail_war_room_refresh_failed",
                    entity_type="email_account",
                    entity_id=account.id,
                    new_value={
                        "account_id": account.id,
                        "error": str(exc)[:240],
                    },
                )
                continue
            watched_autopilot_ran = (
                watched_result.autopilot_sent_count > 0
                or watched_result.autopilot_skipped_count > 0
                or watched_result.autopilot_failed_count > 0
            )
            if (
                settings.gmail_inbound_auto_sync_run_autopilot
                and (watched_result.refused_responses > 0 or watched_result.actionable_refused_threads > 0)
                and not watched_autopilot_ran
            ):
                sync_service.run_autopilot_for_negative_responses(
                    db,
                    current_user,
                    GmailInboundSyncResult(status="success"),
                )
        db.commit()

    worker_status = gmail_inbound_status(db=db, current_user=current_user, provider=provider)
    since_24h = utc_now() - timedelta(hours=24)
    watched_base = select(GmailWatchedThread).where(GmailWatchedThread.email_account_id.in_(account_ids))
    work_base = select(GmailStarredWorkItem).where(GmailStarredWorkItem.email_account_id.in_(account_ids))

    active_watched_threads = int(
        db.scalar(
            watched_base.where(
                GmailWatchedThread.status == "active",
                GmailWatchedThread.star_active.is_(True),
            )
            .with_only_columns(func.count(GmailWatchedThread.id))
            .order_by(None)
        )
        or 0
    )
    watched_threads_total = int(
        db.scalar(watched_base.with_only_columns(func.count(GmailWatchedThread.id)).order_by(None)) or 0
    )
    new_messages_24h = int(
        db.scalar(
            work_base.where(GmailStarredWorkItem.created_at >= since_24h)
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    processed_24h = int(
        db.scalar(
            work_base.where(
                GmailStarredWorkItem.processed_at >= since_24h,
                GmailStarredWorkItem.status.in_(["processed", "positive", "refused", "evidence_needed", "manual_review"]),
            )
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    positive_24h = int(
        db.scalar(
            work_base.where(
                GmailStarredWorkItem.processed_at >= since_24h,
                GmailStarredWorkItem.status == "positive",
            )
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    refused_24h = int(
        db.scalar(
            work_base.where(
                GmailStarredWorkItem.processed_at >= since_24h,
                GmailStarredWorkItem.status == "refused",
            )
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    evidence_24h = int(
        db.scalar(
            work_base.where(
                GmailStarredWorkItem.processed_at >= since_24h,
                GmailStarredWorkItem.status == "evidence_needed",
            )
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    manual_review_24h = int(
        db.scalar(
            work_base.where(
                GmailStarredWorkItem.updated_at >= since_24h,
                GmailStarredWorkItem.status.in_(["manual_review", "failed"]),
            )
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )
    quota_pending_24h = int(
        db.scalar(
            select(func.count(AutopilotAction.id)).where(
                AutopilotAction.created_at >= since_24h,
                AutopilotAction.status.in_(["skipped", "manual_review"]),
                or_(
                    AutopilotAction.skipped_reason.ilike("%quota%"),
                    AutopilotAction.skipped_reason.ilike("%limit%"),
                ),
            )
        )
        or 0
    )
    backlog_remaining = int(
        db.scalar(
            work_base.where(GmailStarredWorkItem.status.in_(["pending", "processing", "manual_review", "failed"]))
            .with_only_columns(func.count(GmailStarredWorkItem.id))
            .order_by(None)
        )
        or 0
    )

    watched_threads = list(
        db.scalars(
            watched_base.options(selectinload(GmailWatchedThread.claim_order).selectinload(ClaimOrder.restaurant))
            .order_by(
                GmailWatchedThread.last_processed_at.asc().nullsfirst(),
                GmailWatchedThread.last_message_at.desc().nullslast(),
                GmailWatchedThread.id.desc(),
            )
            .limit(limit)
        ).all()
    )
    watched_items = [
        GmailWatchedThreadItem(
            id=thread.id,
            email_account_id=thread.email_account_id,
            account_email=account_email_by_id.get(thread.email_account_id),
            gmail_thread_id=thread.gmail_thread_id,
            first_starred_message_id=thread.first_starred_message_id,
            status=thread.status,
            star_active=thread.star_active,
            linked_case_type=thread.linked_case_type,
            linked_case_id=thread.linked_case_id,
            order=_gmail_relance_order_summary(thread.claim_order),
            last_message_at=thread.last_message_at,
            last_processed_at=thread.last_processed_at,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )
        for thread in watched_threads
    ]

    work_items = list(
        db.scalars(
            work_base.options(
                selectinload(GmailStarredWorkItem.inbound_message),
                selectinload(GmailStarredWorkItem.email_account),
            )
            .order_by(GmailStarredWorkItem.created_at.desc(), GmailStarredWorkItem.id.desc())
            .limit(limit)
        ).all()
    )
    work_item_response = [
        GmailWatchedWorkItem(
            id=item.id,
            watched_thread_id=item.watched_thread_id,
            email_account_id=item.email_account_id,
            account_email=item.email_account.email_address if item.email_account else account_email_by_id.get(item.email_account_id),
            gmail_thread_id=item.gmail_thread_id,
            provider_message_id=item.provider_message_id,
            status=item.status,
            reason=item.reason,
            subject=item.inbound_message.subject if item.inbound_message else None,
            from_email=item.inbound_message.from_email if item.inbound_message else None,
            snippet=_short_text(
                (item.inbound_message.snippet or item.inbound_message.body_text) if item.inbound_message else None,
                220,
            ),
            processed_at=item.processed_at,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in work_items
    ]
    sent_drafts = list(db.scalars(_gmail_relance_provider_drafts_query(db, current_user).limit(limit)).all())
    sent_items = [
        GmailRelanceSentItem(
            id=draft.id,
            email_account_id=draft.email_account_id,
            account_email=draft.email_account.email_address if draft.email_account else None,
            provider_thread_id=draft.provider_thread_id,
            provider_message_id=draft.provider_message_id,
            to_email=draft.to_email,
            subject=draft.subject,
            status=draft.status,
            sent_at=draft.sent_at,
            error_message=_short_text(draft.error_message, 180),
            last_error=_short_text(draft.last_error, 180),
            order=_gmail_relance_order_summary(draft.email_draft.order if draft.email_draft else None),
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )
        for draft in sent_drafts
    ]

    latest_cycle = worker_status.last_cycle
    daily_processing_target = max(worker_status.daily_processing_target, 1)
    processed_progress_percent = min(100, int((processed_24h / daily_processing_target) * 100))
    return GmailWarRoomResponse(
        updated_at=utc_now(),
        worker=worker_status,
        summary=GmailWatchedThreadSummary(
            connected_accounts_count=len(connected_accounts),
            active_watched_threads=active_watched_threads,
            watched_threads_total=watched_threads_total,
            new_messages_detected_last_24h=new_messages_24h,
            processed_messages_last_24h=processed_24h,
            positive_responses_last_24h=positive_24h,
            refused_responses_last_24h=refused_24h,
            evidence_requests_last_24h=evidence_24h,
            quota_pending_last_24h=quota_pending_24h,
            manual_review_last_24h=manual_review_24h,
            backlog_remaining=backlog_remaining,
            daily_processing_target=worker_status.daily_processing_target,
            processed_progress_percent=processed_progress_percent,
            quota_blocked=worker_status.quota_blocked,
            quota_retry_after=worker_status.quota_retry_after,
            quota_seconds_until_retry=worker_status.quota_seconds_until_retry,
            latest_cycle_processed_count=latest_cycle.watched_thread_processed_messages if latest_cycle else 0,
            latest_cycle_new_messages=latest_cycle.watched_thread_new_messages if latest_cycle else 0,
        ),
        watched_threads=watched_items,
        work_items=work_item_response,
        sent_relances=sent_items,
    )


@router.post("/v1/email/gmail/inbound/sync", response_model=GmailInboundSyncResponse)
def sync_gmail_inbound(
    payload: GmailInboundSyncRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> GmailInboundSyncResponse:
    settings = get_settings()
    if not settings.email_provider_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email provider is disabled")
    if not settings.gmail_inbound_sync_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gmail inbound sync is disabled")

    connection_status = provider.get_connection_status(db, current_user)
    if not connection_status.connected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Gmail account is not connected")

    request_payload = payload or GmailInboundSyncRequest()
    lookback_days = request_payload.lookback_days or settings.gmail_inbound_sync_lookback_days
    max_messages = request_payload.max_messages or settings.gmail_inbound_max_messages_per_sync
    service = GmailInboundSyncService(provider)
    try:
        result = service.sync(
            db,
            current_user,
            lookback_days=lookback_days,
            max_messages=max_messages,
            analyze_responses=request_payload.analyze_responses,
            apply_reviews=request_payload.apply_reviews,
            run_autopilot_after_sync=request_payload.run_autopilot_after_sync,
        )
    except EmailProviderError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    db.commit()
    return GmailInboundSyncResponse(**result.__dict__)


@router.post("/v1/email/gmail/inbound/analyze", response_model=GmailResponseAnalyzeResponse)
def analyze_gmail_inbound_messages(
    payload: GmailResponseAnalyzeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> GmailResponseAnalyzeResponse:
    request_payload = payload or GmailResponseAnalyzeRequest()
    service = GmailResponseIntelligenceService()
    summary, analyses = service.analyze_inbox(
        db,
        current_user,
        apply_reviews=request_payload.apply_reviews,
        limit=request_payload.limit,
        only_unreviewed=request_payload.only_unreviewed,
    )
    db.commit()
    return GmailResponseAnalyzeResponse(
        analyzed_messages=summary.analyzed_messages,
        applied_reviews=summary.applied_reviews,
        manual_review_messages=summary.manual_review_messages,
        ignored_messages=summary.ignored_messages,
        failed_messages=summary.failed_messages,
        errors=list(summary.errors),
        analyses=[GmailResponseAnalysisRead.model_validate(analysis) for analysis in analyses],
    )


@router.post("/v1/email/inbound-messages/{message_id}/analyze", response_model=GmailResponseAnalysisRead)
def analyze_gmail_inbound_message(
    message_id: int,
    payload: GmailResponseAnalyzeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
) -> GmailResponseAnalysisRead:
    inbound_message = db.get(InboundEmailMessage, message_id)
    if inbound_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbound message not found")
    ensure_can_manage_inbound_message(db, current_user, inbound_message)
    request_payload = payload or GmailResponseAnalyzeRequest()
    service = GmailResponseIntelligenceService()
    try:
        analysis = service.analyze_message(db, current_user, inbound_message, apply_review=request_payload.apply_reviews)
    except ResponseReviewError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    db.commit()
    db.refresh(analysis)
    return GmailResponseAnalysisRead.model_validate(analysis)


@router.get("/v1/email/inbound-messages", response_model=InboundMessagesResponse)
def list_inbound_messages(
    match_status: str | None = Query(default=None),
    order_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InboundMessagesResponse:
    query = visible_inbound_messages_query(db, current_user)
    if match_status:
        query = query.where(InboundEmailMessage.match_status == match_status)
    if order_id is not None:
        order = db.get(ClaimOrder, order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        ensure_can_access_order(db, current_user, order)
        query = query.where(InboundEmailMessage.order_id == order_id)

    messages = db.scalars(
        query.order_by(InboundEmailMessage.received_at.desc().nullslast(), InboundEmailMessage.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return InboundMessagesResponse(
        messages=[InboundEmailMessageRead.model_validate(message) for message in messages],
        limit=limit,
        offset=offset,
    )


@router.get("/v1/orders/{order_id}/email-messages", response_model=OrderEmailMessagesResponse)
def get_order_email_messages(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderEmailMessagesResponse:
    order = db.get(ClaimOrder, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    ensure_can_access_order(db, current_user, order)

    threads = db.scalars(
        select(EmailThread).where(EmailThread.order_id == order_id).order_by(EmailThread.created_at, EmailThread.id)
    ).all()
    inbound_messages = db.scalars(
        select(InboundEmailMessage)
        .where(InboundEmailMessage.order_id == order_id)
        .order_by(InboundEmailMessage.received_at, InboundEmailMessage.id)
    ).all()
    return OrderEmailMessagesResponse(
        threads=[EmailThreadRead.model_validate(thread) for thread in threads],
        inbound_messages=[InboundEmailMessageRead.model_validate(message) for message in inbound_messages],
    )


@router.post("/v1/email/inbound-messages/{message_id}/link", response_model=InboundEmailMessageRead)
def link_inbound_message(
    message_id: int,
    payload: InboundManualLinkRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
    provider: EmailProvider = Depends(get_gmail_provider),
) -> InboundEmailMessageRead:
    inbound_message = db.get(InboundEmailMessage, message_id)
    if inbound_message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inbound message not found")
    order = db.get(ClaimOrder, payload.order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    ensure_can_access_order(db, current_user, order)
    ensure_can_manage_inbound_message(db, current_user, inbound_message)

    service = GmailInboundSyncService(provider)
    service.record_linked_message(db, current_user, inbound_message, order, match_reason="manual_link")
    inbound_message.updated_at = utc_now()
    db.commit()
    db.refresh(inbound_message)
    return InboundEmailMessageRead.model_validate(inbound_message)


def get_active_gmail_account(db: Session, user: User) -> EmailAccount | None:
    return db.scalar(
        select(EmailAccount)
        .where(
            EmailAccount.user_id == user.id,
            EmailAccount.provider == "gmail",
            EmailAccount.disconnected_at.is_(None),
        )
        .order_by(EmailAccount.id.desc())
    )


def get_connected_gmail_accounts(db: Session, user: User) -> list[EmailAccount]:
    return list(
        db.scalars(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == user.id,
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
            )
            .order_by(EmailAccount.connected_at.desc(), EmailAccount.id.desc())
        ).all()
    )


def get_visible_restaurants_for_email_settings(db: Session, user: User) -> list[Restaurant]:
    statement = select(Restaurant).order_by(Restaurant.name, Restaurant.id)
    accessible_ids = get_accessible_restaurant_ids(db, user)
    if accessible_ids is not None:
        if not accessible_ids:
            return []
        statement = statement.where(Restaurant.id.in_(accessible_ids))
    return list(db.scalars(statement).all())


def visible_inbound_messages_query(db: Session, user: User):
    query = select(InboundEmailMessage)
    if user.role == "owner":
        return query

    accessible_restaurant_ids = get_accessible_restaurant_ids(db, user)
    if not accessible_restaurant_ids:
        if user.role == "manager":
            own_account_ids = select(EmailAccount.id).where(EmailAccount.user_id == user.id)
            return query.where(
                and_(
                    InboundEmailMessage.order_id.is_(None),
                    InboundEmailMessage.email_account_id.in_(own_account_ids),
                )
            )
        return query.where(InboundEmailMessage.id == -1)

    accessible_order_ids = select(ClaimOrder.id).where(ClaimOrder.restaurant_id.in_(accessible_restaurant_ids))
    if user.role == "manager":
        own_account_ids = select(EmailAccount.id).where(EmailAccount.user_id == user.id)
        return query.where(
            or_(
                InboundEmailMessage.order_id.in_(accessible_order_ids),
                and_(
                    InboundEmailMessage.order_id.is_(None),
                    InboundEmailMessage.email_account_id.in_(own_account_ids),
                ),
            )
        )

    return query.where(InboundEmailMessage.order_id.in_(accessible_order_ids))


def ensure_can_manage_inbound_message(db: Session, user: User, inbound_message: InboundEmailMessage) -> None:
    if user.role == "owner":
        return
    if inbound_message.order_id is not None:
        existing_order = db.get(ClaimOrder, inbound_message.order_id)
        if existing_order is not None and can_access_restaurant(db, user, existing_order.restaurant_id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inbound message access denied")

    owns_account = (
        db.scalar(
            select(EmailAccount.id).where(
                EmailAccount.id == inbound_message.email_account_id,
                EmailAccount.user_id == user.id,
            )
        )
        is not None
    )
    if not owns_account:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inbound message access denied")
