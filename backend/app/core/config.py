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
    smart_import_preview_expiry_hours: int = 24
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: str | None = None
    gmail_oauth_redirect_uri: str = "http://localhost:8000/v1/email/gmail/oauth/callback"
    gmail_scopes: str = (
        "https://www.googleapis.com/auth/gmail.compose "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/gmail.readonly"
    )
    default_uber_eats_support_email: str = "restaurantsfrance@uber.com"
    email_provider_enabled: bool = False
    email_max_attachment_total_mb: int = 20
    resend_enabled: bool = False
    resend_api_key: str | None = None
    resend_from_email: str = "TENNET <notifications@mail.thetennet.com>"
    resend_reply_to: str | None = None
    resend_domain: str = "mail.thetennet.com"
    resend_api_url: str = "https://api.resend.com/emails"
    gmail_inbound_sync_enabled: bool = False
    gmail_inbound_sync_lookback_days: int = 30
    gmail_inbound_max_messages_per_sync: int = 1000
    gmail_starred_max_messages_per_sync: int = 50000
    gmail_starred_full_history_enabled: bool = True
    gmail_starred_page_size: int = 500
    gmail_starred_max_pages_per_sync: int = 0
    gmail_inbound_auto_sync_enabled: bool = False
    gmail_inbound_auto_sync_continuous_enabled: bool = True
    gmail_inbound_auto_sync_interval_seconds: int = 30
    gmail_inbound_auto_sync_idle_sleep_seconds: int = 1
    gmail_inbound_auto_sync_initial_delay_seconds: int = 5
    gmail_inbound_auto_sync_existing_reprocess_limit: int = 1000
    gmail_inbound_auto_sync_run_autopilot: bool = True
    gmail_inbound_auto_sync_run_workspace_machine: bool = True
    gmail_daily_processing_target: int = 2000
    gmail_quota_retry_safety_seconds: int = 30
    gmail_watched_threads_enabled: bool = True
    gmail_watched_threads_poll_seconds: int = 30
    gmail_watched_threads_full_rescan_minutes: int = 15
    gmail_watched_threads_max_per_cycle: int = 5000
    gmail_watched_threads_batch_per_cycle: int = 100
    gmail_watched_threads_process_new_messages: bool = True
    gmail_support_sender_filter: str = "uber.com"
    followup_1_delay_days: int = 2
    followup_2_delay_days: int = 5
    escalation_delay_days: int = 10
    manual_review_after_days: int = 15
    max_followups_per_order: int = 3
    followup_automatic_send_enabled: bool = False
    export_max_rows: int = 10000
    report_default_lookback_days: int = 90
    uber_reconciliation_default_lookback_days: int = 180
    uber_reconciliation_amount_tolerance: float = 0.01
    uber_reconciliation_min_missing_amount: float = 0.01
    uber_reconciliation_max_results: int = 5000
    evidence_task_high_amount: float = 50
    evidence_task_urgent_amount: float = 100
    evidence_upload_link_expiry_hours: int = 48
    evidence_upload_link_max_uses: int = 3
    ai_evidence_analysis_enabled: bool = False
    ai_evidence_auto_attach_enabled: bool = False
    ai_evidence_high_confidence_threshold: float = 0.90
    ai_evidence_medium_confidence_threshold: float = 0.65
    ai_proof_identity_enabled: bool = True
    ai_gmail_analysis_enabled: bool = True
    ai_gmail_min_confidence: float = 0.70
    bulk_evidence_max_files_per_batch: int = 500
    bulk_evidence_max_zip_size_mb: int = 500
    bulk_evidence_max_file_size_mb: int = 20
    bulk_evidence_allowed_extensions: str = ".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif"
    openai_api_key: str | None = None
    openai_evidence_model: str | None = None
    openai_gmail_model: str | None = None
    openai_request_timeout_seconds: float = 30.0
    ocr_local_enabled: bool = True
    appeals_enabled: bool = True
    appeal_auto_send_enabled: bool = False
    appeal_min_days_between_attempts: int = 2
    appeal_max_attempts_before_escalation: int = 3
    appeal_max_attempts_before_manual_review: int = 6
    appeal_require_new_argument_after_refusal: bool = True
    appeal_allow_same_template_resend: bool = False
    autopilot_enabled: bool = False
    autopilot_initial_claims_enabled: bool = False
    autopilot_followups_enabled: bool = False
    autopilot_appeals_enabled: bool = False
    autopilot_daily_send_limit: int = 1000
    autopilot_per_gmail_account_daily_limit: int = 500
    autopilot_per_restaurant_daily_limit: int = 250
    autopilot_max_candidates_per_run: int = 250
    autopilot_min_amount: float = 5
    autopilot_max_amount_without_owner_review: float = 150
    autopilot_require_complete_evidence: bool = True
    autopilot_require_complete_restaurant_signature: bool = True
    autopilot_require_gmail_connected: bool = True
    autopilot_cooldown_hours: int = 48
    autopilot_refusal_retry_enabled: bool = True
    autopilot_max_appeal_attempts: int = 6
    autopilot_never_close_on_refusal: bool = True
    backend_cors_origins: str | None = None
    cors_origins: str = "http://localhost:3000"
    frontend_url: str | None = None
    api_base_url: str | None = None
    secret_key: str | None = None
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = 120
    login_rate_limit_per_minute: int = 10
    build_sha: str | None = None
    app_version: str = "1.1.1-tennet"

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
