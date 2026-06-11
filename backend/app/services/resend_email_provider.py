import base64
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailDraft, EmailProviderDraft, User
from app.models.domain import utc_now
from app.services.email_provider import EmailConnectionStatus, EmailProviderError, EmailSendResult, InboundEmailPayload
from app.services.file_storage_service import FileStorageError, resolve_evidence_path
from app.services.gmail_email_provider import EvidenceAttachment


class ResendEmailProvider:
    provider = "resend"

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        settings = get_settings()
        enabled = settings.email_provider_enabled and settings.resend_enabled
        connected = bool(enabled and settings.resend_api_key and settings.resend_from_email)
        return EmailConnectionStatus(
            connected=connected,
            provider=self.provider,
            email_address=settings.resend_from_email if connected else None,
            enabled=enabled,
        )

    def disconnect(self, db: Session, user: User) -> None:
        raise EmailProviderError("Resend does not use per-user OAuth accounts", 400)

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        raise EmailProviderError("Resend does not support remote drafts; use manual confirmed send", 400)

    def send_email(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        self.ensure_enabled_and_configured()
        attachments = self.build_evidence_attachments(email_draft, include_evidence)
        response_payload = self.send_resend_email(email_draft, to_email, attachments)
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            provider=self.provider,
            provider_draft_id=str(response_payload.get("id") or ""),
            provider_message_id=str(response_payload.get("id") or ""),
            to_email=to_email,
            subject=email_draft.subject,
            status="sent",
            created_by_user_id=user.id,
            sent_by_user_id=user.id,
            sent_at=utc_now(),
        )
        db.add(provider_draft)
        db.flush()
        return provider_draft

    def send_draft(self, db: Session, user: User, provider_draft: EmailProviderDraft) -> EmailSendResult:
        raise EmailProviderError("Resend sends are created atomically from an internal draft", 400)

    def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
        raise EmailProviderError("Resend inbound sync is not supported", 400)

    def get_message(self, db: Session, user: User, message_id: str) -> InboundEmailPayload:
        raise EmailProviderError("Resend inbound sync is not supported", 400)

    def get_thread(self, db: Session, user: User, thread_id: str) -> dict[str, Any]:
        raise EmailProviderError("Resend inbound sync is not supported", 400)

    def sync_inbound_replies(
        self,
        db: Session,
        user: User,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        raise EmailProviderError("Resend inbound sync is not supported", 400)

    def ensure_enabled_and_configured(self) -> None:
        settings = get_settings()
        if not settings.email_provider_enabled:
            raise EmailProviderError("Email provider is disabled", 503)
        if not settings.resend_enabled:
            raise EmailProviderError("Resend provider is disabled", 503)
        if not settings.resend_api_key:
            raise EmailProviderError("Resend API key is not configured", 503)
        if not settings.resend_from_email:
            raise EmailProviderError("Resend from email is not configured", 503)

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
                    filename=Path(evidence.original_filename).name,
                    mime_type=evidence.mime_type or "application/octet-stream",
                    content=file_path.read_bytes(),
                )
            )
        return attachments

    def send_resend_email(
        self,
        email_draft: EmailDraft,
        to_email: str,
        attachments: list[EvidenceAttachment],
    ) -> dict[str, Any]:
        settings = get_settings()
        payload: dict[str, Any] = {
            "from": settings.resend_from_email,
            "to": [to_email],
            "subject": email_draft.subject,
            "text": email_draft.body,
        }
        if settings.resend_reply_to:
            payload["reply_to"] = [settings.resend_reply_to]
        if attachments:
            payload["attachments"] = [
                {
                    "filename": attachment.filename,
                    "content": base64.b64encode(attachment.content).decode("ascii"),
                    "content_type": attachment.mime_type,
                }
                for attachment in attachments
            ]
        request = Request(
            settings.resend_api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise EmailProviderError(f"Resend API error: HTTP {exc.code}", 502) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise EmailProviderError("Resend API request failed", 502) from exc
