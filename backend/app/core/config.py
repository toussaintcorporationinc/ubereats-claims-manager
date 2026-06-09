from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TENNET"
    app_env: str = "development"
    environment: str | None = None
    debug: bool = False
    docs_enabled: bool = True
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
        "https://www.googleapis.com/auth/gmail.send "
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
    export_max_rows: int = 10000
    report_default_lookback_days: int = 90
    backend_cors_origins: str | None = None
    cors_origins: str = "http://localhost:3000"
    frontend_url: str | None = None
    api_base_url: str | None = None
    secret_key: str | None = None
    access_token_expire_minutes: int = 60
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = 120
    login_rate_limit_per_minute: int = 10
    build_sha: str | None = None
    app_version: str = "1.0.3-tennet"

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
    def runtime_environment(self) -> str:
        return (self.environment or self.app_env).strip().lower()

    @property
    def jwt_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.runtime_environment in {"development", "local", "test", "ci"}:
            return "local-development-secret-key-change-me"
        raise ValueError("SECRET_KEY is required outside local, test, and CI environments")

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.runtime_environment != "production":
            return self

        placeholder_secrets = {
            "change-me",
            "change-me-long-random-secret",
            "local-development-secret-key-change-me",
            "change-me-local-development-only",
        }
        if not self.secret_key or self.secret_key.strip() in placeholder_secrets:
            raise ValueError("SECRET_KEY must be set to a strong non-placeholder value in production")
        if self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must use PostgreSQL in production")
        if "*" in self.cors_origin_list:
            raise ValueError("BACKEND_CORS_ORIGINS cannot contain wildcard origins in production")
        if self.debug:
            raise ValueError("DEBUG must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

