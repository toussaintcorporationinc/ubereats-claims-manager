from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.token_cipher_service import TokenCipherError, TokenCipherService


GMAIL_CLIENT_ID_KEY = "gmail_oauth_client_id"
GMAIL_CLIENT_SECRET_KEY = "gmail_oauth_client_secret"
GMAIL_REDIRECT_URI_KEY = "gmail_oauth_redirect_uri"


@dataclass(frozen=True)
class GmailOAuthRuntimeConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    client_id_source: str
    client_secret_source: str
    redirect_uri_source: str

    @property
    def start_configured(self) -> bool:
        return bool(self.client_id and self.redirect_uri)

    @property
    def callback_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


def _row(db: Session, key: str):
    return db.execute(
        text(
            """
            SELECT key, value_plain, value_encrypted, updated_at
            FROM runtime_settings
            WHERE key = :key
            """
        ),
        {"key": key},
    ).mappings().first()


def _plain_value(db: Session, key: str) -> str | None:
    row = _row(db, key)
    if row is None:
        return None
    value = row["value_plain"]
    return value.strip() if isinstance(value, str) and value.strip() else None


def _secret_value(db: Session, key: str) -> str | None:
    row = _row(db, key)
    if row is None or not row["value_encrypted"]:
        return None
    try:
        value = TokenCipherService().decrypt(row["value_encrypted"])
    except TokenCipherError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def get_gmail_oauth_runtime_config(db: Session) -> GmailOAuthRuntimeConfig:
    settings = get_settings()

    db_client_id = _plain_value(db, GMAIL_CLIENT_ID_KEY)
    db_secret = _secret_value(db, GMAIL_CLIENT_SECRET_KEY)
    db_redirect = _plain_value(db, GMAIL_REDIRECT_URI_KEY)

    env_client_id = (settings.gmail_oauth_client_id or "").strip() or None
    env_secret = (settings.gmail_oauth_client_secret or "").strip() or None
    env_redirect = (settings.gmail_oauth_redirect_uri or "").strip()

    return GmailOAuthRuntimeConfig(
        client_id=db_client_id or env_client_id,
        client_secret=db_secret or env_secret,
        redirect_uri=db_redirect or env_redirect,
        client_id_source="database" if db_client_id else ("environment" if env_client_id else "missing"),
        client_secret_source="database" if db_secret else ("environment" if env_secret else "missing"),
        redirect_uri_source="database" if db_redirect else ("environment" if env_redirect else "missing"),
    )


def save_gmail_oauth_runtime_config(
    db: Session,
    *,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    user_id: int,
) -> GmailOAuthRuntimeConfig:
    normalized_client_id = client_id.strip()
    normalized_redirect_uri = redirect_uri.strip()
    if not normalized_client_id:
        raise ValueError("gmail_oauth_client_id_required")
    if not normalized_redirect_uri.startswith("https://"):
        raise ValueError("gmail_oauth_redirect_uri_must_use_https")

    _upsert_plain(db, GMAIL_CLIENT_ID_KEY, normalized_client_id, user_id)
    _upsert_plain(db, GMAIL_REDIRECT_URI_KEY, normalized_redirect_uri, user_id)

    if client_secret is not None and client_secret.strip():
        encrypted = TokenCipherService().encrypt(client_secret.strip())
        db.execute(
            text(
                """
                INSERT INTO runtime_settings(key, value_plain, value_encrypted, updated_by_user_id, updated_at)
                VALUES (:key, NULL, :value_encrypted, :user_id, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value_plain = NULL,
                    value_encrypted = EXCLUDED.value_encrypted,
                    updated_by_user_id = EXCLUDED.updated_by_user_id,
                    updated_at = NOW()
                """
            ),
            {
                "key": GMAIL_CLIENT_SECRET_KEY,
                "value_encrypted": encrypted,
                "user_id": user_id,
            },
        )

    db.flush()
    return get_gmail_oauth_runtime_config(db)


def _upsert_plain(db: Session, key: str, value: str, user_id: int) -> None:
    db.execute(
        text(
            """
            INSERT INTO runtime_settings(key, value_plain, value_encrypted, updated_by_user_id, updated_at)
            VALUES (:key, :value_plain, NULL, :user_id, NOW())
            ON CONFLICT (key) DO UPDATE SET
                value_plain = EXCLUDED.value_plain,
                value_encrypted = NULL,
                updated_by_user_id = EXCLUDED.updated_by_user_id,
                updated_at = NOW()
            """
        ),
        {"key": key, "value_plain": value, "user_id": user_id},
    )
