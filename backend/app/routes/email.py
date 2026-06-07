from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.auth import ensure_can_access_order, get_current_user, require_owner_or_manager
from app.core.config import get_settings
from app.core.database import get_db
from app.models import EmailDraft, User
from app.schemas.domain import (
    EmailProviderDraftRead,
    GmailConnectionStatus,
    GmailDraftCreate,
    GmailOAuthStartResponse,
)
from app.services.audit import add_audit_log
from app.services.email_provider import EmailProvider, EmailProviderError
from app.services.gmail_email_provider import GmailEmailProvider

router = APIRouter(tags=["email"])


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
