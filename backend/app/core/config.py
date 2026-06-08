from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Uber Eats Claims Manager"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://claims:claims@localhost:5432/claims_manager"
    local_storage_dir: Path = Path("storage")
    evidence_storage_backend: str = "local"
    evidence_storage_dir: Path = Path("data/evidence")
    max_evidence_file_size_mb: int = 15
    import_max_file_size_mb: int = 10
    import_storage_dir: Path = Path("data/imports")
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: str | None = None
    gmail_oauth_redirect_uri: str = "http://localhost:8000/v1/email/gmail/oauth/callback"
    gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.compose "
        "https://www.googleapis.com/auth/gmail.readonly"
    )
    default_uber_eats_support_email: str = "merchants@uber.com"
    email_provider_enabled: bool = False
    email_max_attachment_total_mb: int = 20
    gmail_inbound_sync_enabled: bool = False
    gmail_inbound_sync_lookback_days: int = 30
    gmail_inbound_max_messages_per_sync: int = 100
    gmail_support_sender_filter: str = "uber.com"
    followup_1_delay_days: int = 2
    followup_2_delay_days: int = 5
    escalation_delay_days: int = 10
    manual_review_after_days: int = 15
    max_followups_per_order: int = 3
    followup_automatic_send_enabled: bool = False
    backend_cors_origins: str | None = None
    cors_origins: str = "http://localhost:3000"
    secret_key: str | None = None
    access_token_expire_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        cors_origins = self.backend_cors_origins or self.cors_origins
        return [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

    @property
    def jwt_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.app_env in {"development", "local", "test", "ci"}:
            return "local-development-secret-key-change-me"
        raise ValueError("SECRET_KEY is required outside local, test, and CI environments")


@lru_cache
def get_settings() -> Settings:
    return Settings()

