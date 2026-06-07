from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Uber Eats Claims Manager"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://claims:claims@localhost:5432/claims_manager"
    local_storage_dir: Path = Path("storage")
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

