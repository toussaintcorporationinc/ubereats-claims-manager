from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
V1_1_VERSION = "1.1.1-tennet"


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_v1_1_version_file() -> None:
    assert read("VERSION").strip() == V1_1_VERSION


def test_v1_1_release_docs_exist() -> None:
    required = [
        "docs/RELEASE_NOTES_V1_1.md",
        "docs/RELEASE_NOTES_V1_1_RC.md",
        "docs/KNOWN_LIMITATIONS_V1_1.md",
        "docs/STAGING_DEPLOYMENT.md",
        "docs/STAGING_ACCEPTANCE_PLAN.md",
        "docs/V1_1_ACCEPTANCE_TEST_PLAN.md",
        "docs/DOMAIN_MIGRATION_THETENNET.md",
        "docs/RESEND_SETUP.md",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert missing == []


def test_v1_1_staging_files_exist() -> None:
    required = [
        "docker-compose.staging.yml",
        ".env.staging.example",
        "deploy/Caddyfile.staging",
        "scripts/smoke_test_v1_1.sh",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert missing == []


def test_v1_1_examples_exist() -> None:
    required = [
        "docs/examples/v1_1/README.md",
        "docs/examples/v1_1/uber_orders_report_sample.csv",
        "docs/examples/v1_1/uber_payments_report_sample.csv",
        "docs/examples/v1_1/uber_adjustments_report_sample.csv",
        "docs/examples/v1_1/customer_refunds_sample.csv",
        "docs/examples/v1_1/demo_claim_orders.csv",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert missing == []


def test_v1_1_examples_are_fictitious() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in (REPO_ROOT / "docs/examples/v1_1").glob("*"))
    assert "Restaurant Test" in combined
    assert "Client Test" in combined
    assert "UBER-RC-" in combined
    forbidden = ["gmail.com", "outlook.com", "adresse personnelle", "vrai client", "client reel", "client réel"]
    assert [item for item in forbidden if item in combined.lower()] == []


def test_v1_1_no_misleading_reimbursement_promise() -> None:
    docs = [
        "README.md",
        "docs/RELEASE_NOTES_V1_1.md",
        "docs/RELEASE_NOTES_V1_1_RC.md",
        "docs/KNOWN_LIMITATIONS_V1_1.md",
        "docs/V1_1_ACCEPTANCE_TEST_PLAN.md",
        "docs/RECOVERY_COCKPIT.md",
    ]
    combined = "\n".join(read(path).lower() for path in docs)
    forbidden = [
        "100% remboursement " + "garanti",
        "remboursement " + "garanti",
        "victoire " + "garantie",
    ]
    assert [item for item in forbidden if item in combined] == []


def test_v1_1_dangerous_defaults_are_disabled() -> None:
    env_files = [".env.example", ".env.production.example", ".env.staging.example"]
    required = [
        "EMAIL_PROVIDER_ENABLED=false",
        "GMAIL_INBOUND_SYNC_ENABLED=false",
        "RESEND_ENABLED=false",
        "AI_EVIDENCE_ANALYSIS_ENABLED=false",
        "AI_EVIDENCE_AUTO_ATTACH_ENABLED=false",
        "FOLLOWUP_AUTOMATIC_SEND_ENABLED=false",
        "APPEAL_AUTO_SEND_ENABLED=false",
    ]
    for env_file in env_files:
        content = read(env_file)
        missing = [item for item in required if item not in content]
        assert missing == []
