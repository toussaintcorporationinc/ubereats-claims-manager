import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime, parseaddr
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.models import (
    EmailAccount,
    EmailAccountRestaurantMapping,
    EmailDraft,
    EmailProviderDraft,
    EmailThread,
    InboundEmailMessage,
    User,
)
from app.models.domain import utc_now
from app.services.email_provider import (
    EmailConnectionStatus,
    EmailProviderError,
    EmailSendResult,
    InboundEmailAttachment,
    InboundEmailPayload,
)
from app.services.file_storage_service import FileStorageError, resolve_evidence_path
from app.services.token_cipher_service import TokenCipherService

GMAIL_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
GMAIL_DRAFTS_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_THREADS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/threads"
MAX_INBOUND_ATTACHMENTS = 5
MAX_INBOUND_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_INBOUND_ATTACHMENT_TOTAL_BYTES = 16 * 1024 * 1024
SUPPORTED_INBOUND_ATTACHMENT_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


@dataclass(frozen=True)
class EvidenceAttachment:
    filename: str
    mime_type: str
    content: bytes


@dataclass(frozen=True)
class GmailReplyContext:
    thread_id: str
    message_id: str | None = None
    references: str | None = None
    subject: str | None = None


class GmailEmailProvider:
    provider = "gmail"

    def __init__(self, token_cipher: TokenCipherService | None = None) -> None:
        self.token_cipher = token_cipher or TokenCipherService()

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        if not get_settings().email_provider_enabled:
            return EmailConnectionStatus(connected=False, provider=self.provider, email_address=None, enabled=False)
        account = self.get_active_account(db, user.id)
        return EmailConnectionStatus(
            connected=account is not None,
            provider=self.provider,
            email_address=account.email_address if account else None,
            enabled=True,
        )

    def build_authorization_url(self, user: User) -> str:
        settings = get_settings()
        self.ensure_enabled_and_configured(require_secret=False)
        state = create_access_token(
            str(user.id),
            {"purpose": "gmail_oauth_state", "provider": self.provider},
        )
        query = urlencode(
            {
                "client_id": settings.gmail_oauth_client_id,
                "redirect_uri": settings.gmail_oauth_redirect_uri,
                "response_type": "code",
                "scope": settings.gmail_scopes,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{GMAIL_AUTHORIZATION_URL}?{query}"

    def handle_oauth_callback(self, db: Session, state: str, code: str) -> EmailAccount:
        settings = get_settings()
        self.ensure_enabled_and_configured(require_secret=True)
        user_id = self.decode_oauth_state(state)
        user = db.get(User, user_id)
        if user is None or not user.active:
            raise EmailProviderError("OAuth state user is invalid", 400)

        token_payload = self.exchange_code_for_tokens(code)
        access_token = token_payload.get("access_token")
        if not access_token:
            raise EmailProviderError("Gmail OAuth response did not include an access token", 502)
        refresh_token = token_payload.get("refresh_token")
        expires_in = int(token_payload.get("expires_in") or 3600)
        scopes = token_payload.get("scope") or settings.gmail_scopes
        email_address = self.fetch_email_address(access_token)

        account = self.get_account_by_email(db, user.id, email_address)
        if account is None:
            account = EmailAccount(user_id=user.id, provider=self.provider)
            db.add(account)
        account.email_address = email_address
        account.access_token_encrypted = self.token_cipher.encrypt(access_token)
        if refresh_token:
            account.refresh_token_encrypted = self.token_cipher.encrypt(refresh_token)
        account.token_expires_at = utc_now() + timedelta(seconds=max(expires_in - 60, 60))
        account.scopes = scopes
        account.connected_at = utc_now()
        account.disconnected_at = None
        account.updated_at = utc_now()
        db.flush()
        return account

    def disconnect(self, db: Session, user: User) -> None:
        account = self.get_active_account(db, user.id)
        if account is None:
            return
        account.disconnected_at = utc_now()
        account.access_token_encrypted = None
        account.refresh_token_encrypted = None
        account.updated_at = utc_now()

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        self.ensure_enabled_and_configured(require_secret=True)
        account = self.get_account_for_draft(db, user.id, email_draft)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)

        attachments = self.build_evidence_attachments(email_draft, include_evidence)
        reply_context = self.find_reply_context(db, account, email_draft)
        gmail_subject = build_reply_subject(email_draft.subject, reply_context)
        raw_message = self.build_raw_message(account, email_draft, to_email, attachments, reply_context)
        try:
            access_token = self.access_token_for_external_call(db, account)
            response_payload = self.create_gmail_draft(
                access_token,
                raw_message,
                thread_id=reply_context.thread_id if reply_context else None,
            )
            provider_draft = EmailProviderDraft(
                email_draft_id=email_draft.id,
                email_account_id=account.id,
                provider=self.provider,
                provider_draft_id=str(response_payload.get("id") or ""),
                provider_thread_id=response_payload.get("message", {}).get("threadId")
                or (reply_context.thread_id if reply_context else None),
                to_email=to_email,
                subject=gmail_subject,
                status="provider_draft_created",
                created_by_user_id=user.id,
            )
        except EmailProviderError as exc:
            provider_draft = EmailProviderDraft(
                email_draft_id=email_draft.id,
                email_account_id=account.id if account else None,
                provider=self.provider,
                to_email=to_email,
                subject=email_draft.subject,
                status="failed",
                created_by_user_id=user.id,
                error_message=exc.message,
            )
            db.add(provider_draft)
            db.flush()
            raise

        db.add(provider_draft)
        db.flush()
        return provider_draft

    def send_draft(
        self,
        db: Session,
        user: User,
        provider_draft: EmailProviderDraft,
    ) -> EmailSendResult:
        self.ensure_enabled_and_configured(require_secret=True)
        account = self.get_account_for_provider_draft(db, user.id, provider_draft)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        if not provider_draft.provider_draft_id:
            raise EmailProviderError("Gmail draft id is missing", 409)

        access_token = self.access_token_for_external_call(db, account)
        response_payload = self.send_gmail_draft(access_token, provider_draft.provider_draft_id)
        return EmailSendResult(
            provider_message_id=response_payload.get("id"),
            provider_thread_id=response_payload.get("threadId") or provider_draft.provider_thread_id,
            sent_at=utc_now(),
        )

    def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
        self.ensure_enabled_and_configured(require_secret=True)
        account = self.get_active_account(db, user.id)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        return self.list_messages_for_account(db, account, query=query, max_results=max_results)

    def list_messages_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        max_results: int,
    ) -> list[str]:
        access_token = self.access_token_for_external_call(db, account)
        params = urlencode({"q": query, "maxResults": max_results})
        payload = self.get_json(f"{GMAIL_MESSAGES_URL}?{params}", {"Authorization": f"Bearer {access_token}"})
        return [str(message["id"]) for message in payload.get("messages", []) if message.get("id")]

    def get_message(self, db: Session, user: User, message_id: str) -> InboundEmailPayload:
        self.ensure_enabled_and_configured(require_secret=True)
        account = self.get_active_account(db, user.id)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        return self.get_message_for_account(db, account, message_id)

    def get_message_for_account(
        self,
        db: Session,
        account: EmailAccount,
        message_id: str,
    ) -> InboundEmailPayload:
        access_token = self.access_token_for_external_call(db, account)
        url = f"{GMAIL_MESSAGES_URL}/{quote(message_id, safe='')}?format=full"
        payload = self.get_json(url, {"Authorization": f"Bearer {access_token}"})
        attachments = self.extract_inbound_attachments(access_token, payload)
        return self.parse_gmail_message(payload, attachments=attachments)

    def get_thread(self, db: Session, user: User, thread_id: str) -> dict[str, Any]:
        self.ensure_enabled_and_configured(require_secret=True)
        account = self.get_active_account(db, user.id)
        if account is None:
            raise EmailProviderError("Gmail account is not connected", 409)
        access_token = self.access_token_for_external_call(db, account)
        return self.get_json(
            f"{GMAIL_THREADS_URL}/{quote(thread_id, safe='')}?format=metadata",
            {"Authorization": f"Bearer {access_token}"},
        )

    def sync_inbound_replies(
        self,
        db: Session,
        user: User,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        message_ids = self.list_messages(db, user, query, max_results)
        return [self.get_message(db, user, message_id) for message_id in message_ids]

    def sync_inbound_replies_for_account(
        self,
        db: Session,
        account: EmailAccount,
        *,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        message_ids = self.list_messages_for_account(db, account, query=query, max_results=max_results)
        return [self.get_message_for_account(db, account, message_id) for message_id in message_ids]

    def build_evidence_attachments(self, email_draft: EmailDraft, include_evidence: bool) -> list[EvidenceAttachment]:
        if not include_evidence:
            return []

        max_total_size = get_settings().email_max_attachment_total_mb * 1024 * 1024
        total_size = 0
        attachments: list[EvidenceAttachment] = []
        for evidence in sorted(email_draft.order.evidence_files, key=lambda item: item.id):
            if evidence.deleted_at is not None or not evidence.checksum_sha256:
                continue
            try:
                file_path = resolve_evidence_path(evidence)
            except FileStorageError as exc:
                raise EmailProviderError(f"Evidence file is unavailable: {evidence.original_filename}", 409) from exc
            file_size = evidence.file_size or file_path.stat().st_size
            total_size += file_size
            if total_size > max_total_size:
                raise EmailProviderError("Evidence attachment total size exceeds the configured limit", 413)
            attachments.append(
                EvidenceAttachment(
                    filename=evidence.original_filename,
                    mime_type=evidence.mime_type or "application/octet-stream",
                    content=file_path.read_bytes(),
                )
            )
        return attachments

    def build_raw_message(
        self,
        account: EmailAccount,
        email_draft: EmailDraft,
        to_email: str,
        attachments: list[EvidenceAttachment],
        reply_context: GmailReplyContext | None = None,
    ) -> str:
        message = EmailMessage()
        message["To"] = to_email
        message["Subject"] = build_reply_subject(email_draft.subject, reply_context)
        if account.email_address:
            message["From"] = account.email_address
        if reply_context and reply_context.message_id:
            message["In-Reply-To"] = reply_context.message_id
            references = build_references_header(reply_context.references, reply_context.message_id)
            if references:
                message["References"] = references
        message.set_content(email_draft.body)

        for attachment in attachments:
            maintype, subtype = split_mime_type(attachment.mime_type)
            message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=Path(attachment.filename).name,
            )

        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    def create_gmail_draft(self, access_token: str, raw_message: str, *, thread_id: str | None = None) -> dict:
        payload = {"message": {"raw": raw_message}}
        if thread_id:
            payload["message"]["threadId"] = thread_id
        return self.post_json(
            GMAIL_DRAFTS_URL,
            payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def send_gmail_draft(self, access_token: str, draft_id: str) -> dict:
        return self.post_json(
            GMAIL_DRAFTS_SEND_URL,
            {"id": draft_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def ensure_access_token(self, db: Session, account: EmailAccount) -> str:
        access_token = self.token_cipher.decrypt(account.access_token_encrypted)
        if not access_token:
            raise EmailProviderError("Gmail account is missing an access token", 409)
        expires_at = normalize_datetime(account.token_expires_at)
        if expires_at and expires_at > utc_now():
            return access_token

        refresh_token = self.token_cipher.decrypt(account.refresh_token_encrypted)
        if not refresh_token:
            return access_token

        token_payload = self.refresh_access_token(refresh_token)
        refreshed_token = token_payload.get("access_token")
        if not refreshed_token:
            raise EmailProviderError("Gmail refresh response did not include an access token", 502)
        expires_in = int(token_payload.get("expires_in") or 3600)
        account.access_token_encrypted = self.token_cipher.encrypt(refreshed_token)
        account.token_expires_at = utc_now() + timedelta(seconds=max(expires_in - 60, 60))
        account.updated_at = utc_now()
        db.flush()
        # Persist refreshed tokens immediately so the email_accounts row is not
        # locked while later Gmail API calls or AI analysis are running.
        db.commit()
        return refreshed_token

    def access_token_for_external_call(self, db: Session, account: EmailAccount) -> str:
        access_token = self.ensure_access_token(db, account)
        # Accessing an expired EmailAccount can open a read transaction even when
        # the token is still valid. Close that transaction before network calls
        # so Gmail/OpenAI latency cannot pile up PostgreSQL locks.
        db.commit()
        return access_token

    def exchange_code_for_tokens(self, code: str) -> dict:
        settings = get_settings()
        return self.post_form(
            GMAIL_TOKEN_URL,
            {
                "code": code,
                "client_id": settings.gmail_oauth_client_id or "",
                "client_secret": settings.gmail_oauth_client_secret or "",
                "redirect_uri": settings.gmail_oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    def refresh_access_token(self, refresh_token: str) -> dict:
        settings = get_settings()
        return self.post_form(
            GMAIL_TOKEN_URL,
            {
                "refresh_token": refresh_token,
                "client_id": settings.gmail_oauth_client_id or "",
                "client_secret": settings.gmail_oauth_client_secret or "",
                "grant_type": "refresh_token",
            },
        )

    def fetch_email_address(self, access_token: str) -> str | None:
        request = Request(GMAIL_PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None
        return payload.get("emailAddress")

    def post_form(self, url: str, payload: dict[str, str]) -> dict:
        encoded_payload = urlencode(payload).encode("utf-8")
        request = Request(
            url,
            data=encoded_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        return self.read_json_response(request)

    def post_json(self, url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        return self.read_json_response(request)

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> dict:
        request = Request(url, headers=headers or {}, method="GET")
        return self.read_json_response(request)

    def read_json_response(self, request: Request) -> dict:
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise EmailProviderError(f"Gmail API error: HTTP {exc.code}", 502) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmailProviderError("Gmail API request failed", 502) from exc

    def decode_oauth_state(self, state: str) -> int:
        try:
            payload = decode_access_token(state)
            if payload.get("purpose") != "gmail_oauth_state" or payload.get("provider") != self.provider:
                raise ValueError("Invalid OAuth state purpose")
            return int(payload.get("sub", ""))
        except (TypeError, ValueError) as exc:
            raise EmailProviderError("Invalid OAuth state", 400) from exc

    def get_active_account(self, db: Session, user_id: int) -> EmailAccount | None:
        return db.scalar(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == user_id,
                EmailAccount.provider == self.provider,
                EmailAccount.disconnected_at.is_(None),
            )
            .order_by(EmailAccount.id.desc())
        )

    def get_account_by_email(self, db: Session, user_id: int, email_address: str | None) -> EmailAccount | None:
        if not email_address:
            return None
        return db.scalar(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == user_id,
                EmailAccount.provider == self.provider,
                EmailAccount.email_address == email_address,
            )
            .order_by(EmailAccount.id.desc())
        )

    def get_account_for_restaurant(self, db: Session, user_id: int, restaurant_id: int | None) -> EmailAccount | None:
        if restaurant_id is None:
            return self.get_active_account(db, user_id)
        mapped_account = db.scalar(
            select(EmailAccount)
            .join(EmailAccountRestaurantMapping, EmailAccountRestaurantMapping.email_account_id == EmailAccount.id)
            .where(
                EmailAccountRestaurantMapping.restaurant_id == restaurant_id,
                EmailAccount.user_id == user_id,
                EmailAccount.provider == self.provider,
                EmailAccount.disconnected_at.is_(None),
            )
        )
        return mapped_account or self.get_active_account(db, user_id)

    def get_account_for_draft(self, db: Session, user_id: int, email_draft: EmailDraft) -> EmailAccount | None:
        restaurant_id = email_draft.order.restaurant_id if email_draft.order else None
        return self.get_account_for_restaurant(db, user_id, restaurant_id)

    def get_account_for_provider_draft(
        self,
        db: Session,
        user_id: int,
        provider_draft: EmailProviderDraft,
    ) -> EmailAccount | None:
        if provider_draft.email_account_id is not None:
            account = db.get(EmailAccount, provider_draft.email_account_id)
            if (
                account is not None
                and account.user_id == user_id
                and account.provider == self.provider
                and account.disconnected_at is None
            ):
                return account
        return self.get_account_for_draft(db, user_id, provider_draft.email_draft)

    def find_reply_context(
        self,
        db: Session,
        account: EmailAccount,
        email_draft: EmailDraft,
    ) -> GmailReplyContext | None:
        if email_draft.order_id is None:
            return None

        inbound_message = db.scalar(
            select(InboundEmailMessage)
            .where(
                InboundEmailMessage.email_account_id == account.id,
                InboundEmailMessage.order_id == email_draft.order_id,
                InboundEmailMessage.provider == self.provider,
                InboundEmailMessage.provider_thread_id.is_not(None),
            )
            .order_by(InboundEmailMessage.id.desc())
        )
        if inbound_message and inbound_message.provider_thread_id:
            headers = inbound_message.raw_headers_json or {}
            return GmailReplyContext(
                thread_id=inbound_message.provider_thread_id,
                message_id=extract_header_value(headers, "message-id"),
                references=extract_header_value(headers, "references"),
                subject=inbound_message.subject,
            )

        email_thread = db.scalar(
            select(EmailThread)
            .where(
                EmailThread.order_id == email_draft.order_id,
                EmailThread.provider == self.provider,
                EmailThread.thread_id.is_not(None),
            )
            .order_by(EmailThread.id.desc())
        )
        if email_thread and email_thread.thread_id:
            message_id = email_thread.message_id if looks_like_rfc_message_id(email_thread.message_id) else None
            return GmailReplyContext(thread_id=email_thread.thread_id, message_id=message_id, subject=email_thread.subject)

        provider_draft = db.scalar(
            select(EmailProviderDraft)
            .join(EmailDraft, EmailDraft.id == EmailProviderDraft.email_draft_id)
            .where(
                EmailDraft.order_id == email_draft.order_id,
                EmailProviderDraft.provider == self.provider,
                EmailProviderDraft.email_account_id == account.id,
                EmailProviderDraft.provider_thread_id.is_not(None),
            )
            .order_by(EmailProviderDraft.id.desc())
        )
        if provider_draft and provider_draft.provider_thread_id:
            message_id = (
                provider_draft.provider_message_id
                if looks_like_rfc_message_id(provider_draft.provider_message_id)
                else None
            )
            return GmailReplyContext(
                thread_id=provider_draft.provider_thread_id,
                message_id=message_id,
                subject=provider_draft.subject,
            )
        return None

    def ensure_enabled_and_configured(self, *, require_secret: bool) -> None:
        settings = get_settings()
        if not settings.email_provider_enabled:
            raise EmailProviderError("Email provider is disabled", 503)
        if not settings.gmail_oauth_client_id or not settings.gmail_oauth_redirect_uri:
            raise EmailProviderError("Gmail OAuth is not configured", 503)
        if require_secret and not settings.gmail_oauth_client_secret:
            raise EmailProviderError("Gmail OAuth client secret is not configured", 503)

    def extract_inbound_attachments(self, access_token: str, payload: dict[str, Any]) -> list[InboundEmailAttachment]:
        attachments: list[InboundEmailAttachment] = []
        total_size = 0
        message_id = str(payload.get("id") or "")
        if not message_id:
            return attachments
        for part in iter_message_parts(payload.get("payload", {})):
            if len(attachments) >= MAX_INBOUND_ATTACHMENTS:
                break
            filename = str(part.get("filename") or "").strip()
            if not filename:
                continue
            mime_type = str(part.get("mimeType") or "application/octet-stream").lower()
            if mime_type not in SUPPORTED_INBOUND_ATTACHMENT_MIME_TYPES:
                continue
            body = part.get("body") or {}
            size = int(body.get("size") or 0)
            if size > MAX_INBOUND_ATTACHMENT_BYTES:
                continue
            data = body.get("data")
            if data:
                content = decode_gmail_bytes(str(data))
            else:
                attachment_id = body.get("attachmentId")
                if not attachment_id:
                    continue
                content = self.fetch_message_attachment(access_token, message_id, str(attachment_id))
            if not content or len(content) > MAX_INBOUND_ATTACHMENT_BYTES:
                continue
            if total_size + len(content) > MAX_INBOUND_ATTACHMENT_TOTAL_BYTES:
                break
            total_size += len(content)
            attachments.append(
                InboundEmailAttachment(
                    filename=Path(filename).name,
                    mime_type=mime_type,
                    content=content,
                )
            )
        return attachments

    def fetch_message_attachment(self, access_token: str, message_id: str, attachment_id: str) -> bytes:
        payload = self.get_json(
            f"{GMAIL_MESSAGES_URL}/{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}",
            {"Authorization": f"Bearer {access_token}"},
        )
        return decode_gmail_bytes(str(payload.get("data") or ""))

    def parse_gmail_message(
        self,
        payload: dict[str, Any],
        *,
        attachments: list[InboundEmailAttachment] | None = None,
    ) -> InboundEmailPayload:
        headers = extract_headers(payload.get("payload", {}))
        body_text = extract_text_plain(payload.get("payload", {}))
        received_at = parse_received_at(payload, headers)
        from_email = parseaddr(headers.get("from", ""))[1] or headers.get("from")
        to_email = parseaddr(headers.get("to", ""))[1] or headers.get("to")
        return InboundEmailPayload(
            provider_message_id=str(payload.get("id") or ""),
            provider_thread_id=payload.get("threadId"),
            gmail_history_id=str(payload.get("historyId")) if payload.get("historyId") is not None else None,
            from_email=from_email,
            to_email=to_email,
            subject=headers.get("subject"),
            snippet=payload.get("snippet"),
            body_text=body_text[:20000] if body_text else None,
            received_at=received_at,
            raw_headers=headers,
            provider_labels=[str(label) for label in payload.get("labelIds", []) if label],
            attachments=attachments or [],
        )


def split_mime_type(mime_type: str) -> tuple[str, str]:
    if "/" not in mime_type:
        return "application", "octet-stream"
    maintype, subtype = mime_type.split("/", 1)
    return maintype, subtype


def extract_header_value(headers: dict[str, Any], header_name: str) -> str | None:
    wanted = header_name.strip().casefold()
    for key, value in headers.items():
        if str(key).strip().casefold() == wanted and value:
            return str(value)
    return None


def looks_like_rfc_message_id(value: str | None) -> bool:
    cleaned = str(value or "").strip()
    return cleaned.startswith("<") and cleaned.endswith(">") and "@" in cleaned


def build_references_header(existing_references: str | None, message_id: str | None) -> str | None:
    references = str(existing_references or "").strip()
    message_id = str(message_id or "").strip()
    if message_id and message_id not in references:
        references = f"{references} {message_id}".strip()
    return references or None


def build_reply_subject(default_subject: str, reply_context: GmailReplyContext | None) -> str:
    if not reply_context or not reply_context.subject:
        return default_subject
    subject = reply_context.subject.strip()
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in payload.get("headers", []) or []:
        name = str(header.get("name") or "").lower()
        value = str(header.get("value") or "")
        if name:
            headers[name] = value
    return headers


def extract_text_plain(payload: dict[str, Any]) -> str:
    body = payload.get("body") or {}
    data = body.get("data")
    mime_type = payload.get("mimeType")
    if data and (mime_type == "text/plain" or not payload.get("parts")):
        return decode_gmail_body(data)

    chunks: list[str] = []
    for part in payload.get("parts", []) or []:
        text = extract_text_plain(part)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def iter_message_parts(payload: dict[str, Any]):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from iter_message_parts(part)


def decode_gmail_body(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def decode_gmail_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}")
    except (ValueError, TypeError):
        return b""


def parse_received_at(payload: dict[str, Any], headers: dict[str, str]) -> datetime | None:
    internal_date = payload.get("internalDate")
    if internal_date is not None:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            pass
    date_header = headers.get("date")
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    return normalize_datetime(parsed)
