from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, get_current_user, require_owner_or_manager
from app.core.config import get_settings
from app.core.database import get_db
from app.models import EmailDraft, EmailProviderDraft, EmailThread, User
from app.models.domain import utc_now
from app.schemas.domain import (
    EmailProviderDraftRead,
    GmailConnectionStatus,
    GmailDraftCreate,
    GmailDraftSendRequest,
    GmailDraftSendResponse,
    GmailOAuthStartResponse,
)
from app.services.audit import add_audit_log
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.gmail_email_provider import GmailEmailProvider

router = APIRouter(tags=["email"])
FINAL_ORDER_STATUSES = {"accepted", "payment_confirmed", "refused", "closed"}


def get_gmail_provider() -> EmailProvider:
    return GmailEmailProvider()


@router.get("/v1/email/gmail/status", response_model=GmailConnectionStatus)
def gmail_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: EmailProvider = Depends(get_gmail_provider),
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
        "<html><body><h1>Gmail connected</h1><p>You can close this window and return to Claims Manager.</p></body></html>"
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
    db.commit()
    db.refresh(provider_draft)

    return GmailDraftSendResponse(
        provider_draft_id=provider_draft.provider_draft_id or provider_draft_id,
        status=provider_draft.status,
        provider_message_id=provider_draft.provider_message_id,
        provider_thread_id=provider_draft.provider_thread_id,
        sent_at=provider_draft.sent_at,
    )
