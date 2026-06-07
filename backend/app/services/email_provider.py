from dataclasses import dataclass
from typing import Protocol

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
