import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.rate_limit import reset_rate_limit_state


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_works_with_test_database(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["database"] == "ok"


def test_version_does_not_return_secrets(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/version")

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload).lower()
    assert payload["service"] == "Uber Eats Claims Manager"
    assert "secret" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized


def test_production_config_refuses_secret_key_placeholder() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="change-me-long-random-secret",
            database_url="postgresql+psycopg://claims:claims@db:5432/claims_manager",
            backend_cors_origins="https://app.example.com",
        )


def test_production_config_refuses_sqlite_database_url() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="production-secret-key-with-enough-entropy",
            database_url="sqlite:///./local.db",
            backend_cors_origins="https://app.example.com",
        )


def test_production_config_refuses_cors_wildcard() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="production-secret-key-with-enough-entropy",
            database_url="postgresql+psycopg://claims:claims@db:5432/claims_manager",
            backend_cors_origins="*",
        )


def test_login_rate_limit_blocks_excess_attempts(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_rate_limit_state()

    try:
        payload = {"email": "owner@example.com", "password": "wrong-password"}
        assert client.post("/v1/auth/login", json=payload).status_code == 401
        assert client.post("/v1/auth/login", json=payload).status_code == 401
        response = client.post("/v1/auth/login", json=payload)
        assert response.status_code == 429
        assert response.json()["detail"] == "Rate limit exceeded"
    finally:
        reset_rate_limit_state()
        get_settings.cache_clear()
