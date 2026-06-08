from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_release_health_ready_and_version(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/health").status_code == 200
    assert unauthenticated_client.get("/ready").status_code == 200

    response = unauthenticated_client.get("/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "Uber Eats Claims Manager"
    assert payload["version"] == "1.0.0-v1"
    assert payload["environment"] in {"ci", "test"}
    assert payload["commit"] == "unknown"
    serialized = str(payload).lower()
    assert "secret" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized


def test_final_go_live_documents_exist() -> None:
    docs = [
        "docs/GO_LIVE_RUNBOOK.md",
        "docs/ACCEPTANCE_TEST_PLAN.md",
        "docs/USER_GUIDE.md",
        "docs/ADMIN_GUIDE.md",
        "docs/RELEASE_NOTES_V1.md",
        "docs/ROLLBACK_PLAN.md",
        "docs/GMAIL_PRODUCTION_VALIDATION.md",
        "docs/KNOWN_LIMITATIONS_V1.md",
    ]

    missing = [path for path in docs if not (REPO_ROOT / path).is_file()]
    assert missing == []


def test_production_release_files_exist() -> None:
    files = [
        "docker-compose.prod.yml",
        ".env.production.example",
        "deploy/Caddyfile",
        "scripts/backup_postgres.sh",
        "scripts/restore_postgres.sh",
        "scripts/backup_evidence_files.sh",
        "scripts/healthcheck.sh",
        "scripts/smoke_test.sh",
        "VERSION",
    ]

    missing = [path for path in files if not (REPO_ROOT / path).is_file()]
    assert missing == []
    assert (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.0.0-v1"


def test_env_production_example_contains_critical_variables() -> None:
    env_text = (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8")
    required = [
        "ENVIRONMENT=production",
        "SECRET_KEY=",
        "DATABASE_URL=",
        "BACKEND_CORS_ORIGINS=",
        "NEXT_PUBLIC_API_BASE_URL=",
        "EMAIL_PROVIDER_ENABLED=false",
        "GMAIL_INBOUND_SYNC_ENABLED=false",
        "FOLLOWUP_AUTOMATIC_SEND_ENABLED=false",
        "EXPORT_MAX_ROWS=",
        "RATE_LIMIT_ENABLED=true",
    ]

    missing = [item for item in required if item not in env_text]
    assert missing == []


def test_demo_orders_are_fictitious() -> None:
    demo_path = REPO_ROOT / "docs/examples/demo_orders.csv"
    content = demo_path.read_text(encoding="utf-8")

    assert "Restaurant Demo" in content
    assert "UBER-DEMO-" in content
    assert "Client Test" in content
    assert "@" not in content
    assert "gmail.com" not in content.lower()
    assert "outlook.com" not in content.lower()
