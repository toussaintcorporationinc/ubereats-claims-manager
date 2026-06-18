from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

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
    EmailAccount,
    EmailAccountRestaurantMapping,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    GmailSyncState,
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
    GmailRestaurantMappingRead,
    GmailRestaurantMappingUpdate,
    GmailResponseAnalysisRead,
    GmailResponseAnalyzeRequest,
    GmailResponseAnalyzeResponse,
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
from app.services.gmail_inbound_sync_service import GmailInboundSyncService
from app.services.gmail_response_intelligence_service import GmailResponseIntelligenceService
from app.services.resend_email_provider import ResendEmailProvider
from app.services.response_review_service import ResponseReviewError

router = APIRouter(tags=["email"])
FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def get_gmail_provider() -> EmailProvider:
    return GmailEmailProvider()


def get_resend_provider() -> ResendEmailProvider:
    return ResendEmailProvider()


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
    account = get_active_gmail_account(db, current_user)
    sync_state = None
    if account is not None:
        sync_state = db.scalar(select(GmailSyncState).where(GmailSyncState.email_account_id == account.id))
    return GmailInboundStatusResponse(
        enabled=settings.email_provider_enabled and settings.gmail_inbound_sync_enabled,
        connected=connection_status.connected,
        auto_sync_enabled=settings.gmail_inbound_auto_sync_enabled,
        auto_sync_interval_seconds=settings.gmail_inbound_auto_sync_interval_seconds,
        auto_sync_run_autopilot=settings.gmail_inbound_auto_sync_run_autopilot,
        auto_sync_run_workspace_machine=settings.gmail_inbound_auto_sync_run_workspace_machine,
        autopilot_enabled=settings.autopilot_enabled,
        autopilot_followups_enabled=settings.autopilot_followups_enabled,
        autopilot_appeals_enabled=settings.autopilot_appeals_enabled,
        ai_gmail_analysis_enabled=settings.ai_gmail_analysis_enabled,
        last_sync_at=sync_state.last_sync_at if sync_state else None,
        last_success_at=sync_state.last_success_at if sync_state else None,
        status=sync_state.status if sync_state else None,
        last_error=sync_state.last_error if sync_state else None,
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
