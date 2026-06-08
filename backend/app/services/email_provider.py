from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models import EmailDraft, EmailProviderDraft, User


class EmailProviderError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class EmailConnectionStatus:
    connected: bool
    provider: str
    email_address: str | None
    enabled: bool


@dataclass(frozen=True)
class EmailSendResult:
    provider_message_id: str | None
    provider_thread_id: str | None
    sent_at: datetime


@dataclass(frozen=True)
class InboundEmailPayload:
    provider_message_id: str
    provider_thread_id: str | None
    gmail_history_id: str | None
    from_email: str | None
    to_email: str | None
    subject: str | None
    snippet: str | None
    body_text: str | None
    received_at: datetime | None
    raw_headers: dict[str, Any]


class EmailProvider(Protocol):
    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        ...

    def disconnect(self, db: Session, user: User) -> None:
        ...

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        ...

    def send_draft(
        self,
        db: Session,
        user: User,
        provider_draft: EmailProviderDraft,
    ) -> EmailSendResult:
        ...

    def list_messages(self, db: Session, user: User, query: str, max_results: int) -> list[str]:
        ...

    def get_message(self, db: Session, user: User, message_id: str) -> InboundEmailPayload:
        ...

    def get_thread(self, db: Session, user: User, thread_id: str) -> dict[str, Any]:
        ...

    def sync_inbound_replies(
        self,
        db: Session,
        user: User,
        query: str,
        max_results: int,
    ) -> list[InboundEmailPayload]:
        ...
