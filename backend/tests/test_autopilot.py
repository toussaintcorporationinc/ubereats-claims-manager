from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import (
    AppealAttempt,
    AppealWorkflow,
    AuditLog,
    AutopilotAction,
    ClaimOrder,
    ClaimResponseReview,
    EmailAccount,
    EmailDraft,
    EvidenceFile,
    EmailProviderDraft,
    FollowUpTask,
    GmailResponseAnalysis,
    InboundEmailMessage,
    RefusalAnalysis,
    Restaurant,
    User,
)
from app.models.domain import utc_now
from app.services.openai_structured_analysis_service import AIProofExtraction, OpenAIStructuredAnalysisService
from app.routes.email import get_gmail_provider
from app.services.autopilot_service import (
    gmail_account_send_pacing_active,
    gmail_account_sent_last_24_hours_count,
    iter_candidates,
    resume_next_prepared_provider_draft,
)
from app.services.autopilot_identity_repair_service import find_or_create_order_from_starred_text
from app.services.email_provider import EmailConnectionStatus, EmailSendResult, InboundEmailPayload


class FakeAutopilotGmailProvider:
    provider = "gmail"

    def __init__(self) -> None:
        self.thread_payloads: dict[str, list[InboundEmailPayload]] = {}
        self.sent_draft_ids: list[int] = []

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        if not get_settings().email_provider_enabled:
            return EmailConnectionStatus(connected=False, provider="gmail", email_address=None, enabled=False)
        account = db.scalar(
            select(EmailAccount).where(
                EmailAccount.user_id == user.id,
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
            )
        )
        return EmailConnectionStatus(
            connected=account is not None,
            provider="gmail",
            email_address=account.email_address if account else None,
            enabled=True,
        )

    def create_draft(
        self,
        db: Session,
        user: User,
        email_draft: EmailDraft,
        to_email: str,
        include_evidence: bool,
    ) -> EmailProviderDraft:
        account = db.scalar(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == user.id,
                EmailAccount.provider == "gmail",
                EmailAccount.disconnected_at.is_(None),
            )
            .order_by(EmailAccount.id.asc())
        )
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
            email_account_id=account.id if account else None,
            provider="gmail",
            provider_draft_id=f"fake-autopilot-{email_draft.id}-{utc_now().timestamp()}",
            provider_thread_id=f"fake-thread-{email_draft.id}",
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        return provider_draft

    def send_draft(self, db: Session, user: User, provider_draft: EmailProviderDraft) -> EmailSendResult:
        self.sent_draft_ids.append(provider_draft.id)
        return EmailSendResult(
            provider_message_id=f"fake-message-{provider_draft.id}",
            provider_thread_id=provider_draft.provider_thread_id or f"fake-thread-{provider_draft.id}",
            sent_at=utc_now(),
        )

    def get_thread_messages_for_account(
        self,
        db: Session,
        account: EmailAccount,
        thread_id: str,
        *,
        include_attachments: bool = False,
    ) -> list[InboundEmailPayload]:
        return self.thread_payloads.get(thread_id, [])


@pytest.fixture()
def fake_gmail_provider() -> Generator[FakeAutopilotGmailProvider, None, None]:
    provider = FakeAutopilotGmailProvider()
    app.dependency_overrides[get_gmail_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_gmail_provider, None)


@pytest.fixture()
def autopilot_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_INITIAL_CLAIMS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_FOLLOWUPS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_APPEALS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DAILY_SEND_LIMIT", "50")
    monkeypatch.setenv("AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT", "20")
    monkeypatch.setenv("AUTOPILOT_COOLDOWN_HOURS", "48")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def create_restaurant(client: TestClient, name: str = "AutoPilot Restaurant") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={
            "name": name,
            "address": "108 Avenue du Marechal Foch, Meaux, 77100",
            "phone_number": "0605807385",
            "sender_email": "claims@example.com",
            "autopilot_enabled": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_ready_order(client: TestClient, restaurant_id: int, order_number: str = "AUTO-001") -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "customer_name": "Client Test",
            "order_date": "2026-06-01",
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
    )
    assert response.status_code == 201
    order = response.json()
    for evidence_type in ("cancellation_proof", "preparation_proof"):
        evidence_response = client.post(
            f"/v1/orders/{order['id']}/evidence",
            json={
                "evidence_type": evidence_type,
                "original_filename": f"{evidence_type}.png",
                "storage_path": f"storage/evidence/{evidence_type}.png",
                "mime_type": "image/png",
                "file_size": 1024,
            },
        )
        assert evidence_response.status_code == 201
    validate_response = client.post(f"/v1/orders/{order['id']}/validate")
    assert validate_response.status_code == 200
    return validate_response.json()


def test_starred_gmail_legacy_name_creates_order_for_asian_passion(
    client: TestClient,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(client, name="Asian Passion")
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None

    order = find_or_create_order_from_starred_text(
        db_session,
        owner,
        (
            "Bonsoir, je conteste l'annulation de la commande d'Antoine N, "
            "numero de commande 3D22E le 10/05/2026. La commande a ete preparee.\n\n"
            "Crousty Best"
        ),
    )

    assert order is not None
    assert order.restaurant_id == restaurant["id"]
    assert order.uber_order_number == "3D22E"
    assert order.customer_name == "Antoine N"


def test_starred_gmail_instruction_text_does_not_create_fake_order(
    client: TestClient,
    db_session: Session,
) -> None:
    create_restaurant(client, name="King Krousty")
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None

    order = find_or_create_order_from_starred_text(
        db_session,
        owner,
        (
            "Bonjour, commande de 1. *Respectez scrupuleusement vos horaires* "
            "numero de commande PRENDRE pour le restaurant King Krousty."
        ),
    )

    assert order is None
    assert db_session.scalar(select(ClaimOrder).where(ClaimOrder.uber_order_number == "PRENDRE")) is None


def add_gmail_account(db_session: Session) -> EmailAccount:
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    account = EmailAccount(
        user_id=owner.id,
        provider="gmail",
        email_address="owner@example.com",
        access_token_encrypted="fake",
        refresh_token_encrypted="fake",
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def add_starred_inbound_message(
    db_session: Session,
    order: ClaimOrder,
    account: EmailAccount,
    *,
    received_at: datetime | None = None,
) -> None:
    db_session.add(
        InboundEmailMessage(
            email_account_id=account.id,
            order_id=order.id,
            provider="gmail",
            provider_message_id=f"starred-{order.uber_order_number}",
            provider_thread_id=f"thread-{order.uber_order_number}",
            from_email="restaurantsfrance@uber.com",
            to_email=account.email_address,
            subject=f"Re: commande {order.uber_order_number}",
            body_text="Votre demande est refusee.",
            provider_labels_json=["STARRED"],
            match_status="linked",
            match_reason="thread_id_match",
            review_status="reviewed",
            received_at=received_at or utc_now(),
        )
    )
    db_session.commit()


def add_starred_identity_message(db_session: Session, order: ClaimOrder, account: EmailAccount) -> None:
    db_session.add(
        InboundEmailMessage(
            email_account_id=account.id,
            order_id=order.id,
            provider="gmail",
            provider_message_id=f"starred-identity-{order.id}",
            provider_thread_id=f"thread-identity-{order.id}",
            from_email=account.email_address,
            to_email="restaurantsfrance@uber.com",
            subject="Contestation de remboursement de commande",
            body_text=(
                "Bonjour je veux contester la demande de remboursement de Yoann O "
                "numero de commande F93BA du 18/06/2026 car sa commande a bien ete preparee. "
                "Montant concerne : 24.99 EUR\n\n"
                "Frit Dodo\n108 Avenue du Marechal Foch, Meaux, 77100\n0605807385"
            ),
            provider_labels_json=["STARRED", "SENT"],
            match_status="linked",
            match_reason="thread_id_match",
            review_status="reviewed",
            received_at=utc_now(),
        )
    )
    db_session.commit()


def test_health_public_still_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200


def test_autopilot_dry_run_lists_candidates_without_sending(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    order = create_ready_order(client, restaurant["id"])
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/dry-run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"]})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["total_candidates"] == 1
    assert payload["actions"][0]["case_id"] == order["order_id"]
    assert payload["actions"][0]["status"] == "candidate"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_dry_run_does_not_call_ai_for_complete_order_identity(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_ai_call(*args, **kwargs):
        raise AssertionError("complete order identity must not trigger AI analysis")

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_order_identity_text", unexpected_ai_call)
    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_proof", unexpected_ai_call)

    restaurant = create_restaurant(client, "Asian Passion")
    order = ClaimOrder(
        restaurant_id=restaurant["id"],
        uber_order_number="AP-COMPLETE-001",
        customer_name="Client Complet",
        order_date=date(2026, 7, 20),
        order_amount=Decimal("29.90"),
        currency="EUR",
        accepted_by_restaurant=True,
        prepared_before_cancellation=True,
        status="refused",
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        AppealWorkflow(
            case_type="claim_order",
            case_id=order.id,
            restaurant_id=order.restaurant_id,
            claim_order_id=order.id,
            status="appeal_needed",
            refusal_count=1,
            next_action_type="create_appeal_draft",
            next_action_at=utc_now() - timedelta(hours=1),
        )
    )
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)

    response = client.post(
        "/v1/autopilot/dry-run",
        json={"mode": "appeals", "restaurant_id": restaurant["id"]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["total_candidates"] == 1
    assert payload["actions"][0]["reason"] == "dry_run_candidate"


def test_autopilot_candidate_iteration_respects_run_limit(
    client: TestClient,
    db_session: Session,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    created = [
        create_ready_order(client, restaurant["id"], f"AUTO-LIMIT-{index}")["order_id"]
        for index in range(5)
    ]
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None

    candidates = iter_candidates(
        db_session,
        owner,
        "initial_claims",
        restaurant["id"],
        max_candidates=2,
    )

    assert [candidate.case_id for candidate in candidates] == created[:2]


def test_autopilot_run_refuses_when_disabled(
    client: TestClient,
    fake_gmail_provider: FakeAutopilotGmailProvider,
) -> None:
    response = client.post("/v1/autopilot/run", json={"mode": "all", "dry_run": False})

    assert response.status_code == 409
    assert response.json()["detail"] == "autopilot_disabled"


def test_autopilot_run_refuses_when_gmail_disconnected(
    client: TestClient,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    create_ready_order(client, restaurant["id"])

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 409
    assert response.json()["detail"] == "gmail_account_not_connected"


def test_autopilot_sends_initial_claim_for_ready_order(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"])
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    assert order.status == "sent"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is not None
    assert db_session.scalar(select(AuditLog).where(AuditLog.action == "autopilot.initial_claim.sent")) is not None


def test_autopilot_does_not_send_missing_evidence_order(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant["id"],
            "uber_order_number": "AUTO-MISSING",
            "order_amount": "24.90",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201
    add_gmail_account(db_session)

    run_response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert run_response.status_code == 201
    assert run_response.json()["run"]["sent_count"] == 0
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_respects_daily_limit(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_INITIAL_CLAIMS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DAILY_SEND_LIMIT", "0")
    get_settings.cache_clear()
    restaurant = create_restaurant(client)
    create_ready_order(client, restaurant["id"])
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    assert response.json()["actions"][0]["skipped_reason"] == "daily_send_limit_reached"
    get_settings.cache_clear()


def test_autopilot_respects_per_restaurant_limit(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_INITIAL_CLAIMS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_PER_RESTAURANT_DAILY_LIMIT", "0")
    get_settings.cache_clear()
    restaurant = create_restaurant(client)
    create_ready_order(client, restaurant["id"])
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    assert response.json()["actions"][0]["skipped_reason"] == "per_restaurant_daily_limit_reached"
    get_settings.cache_clear()


def test_autopilot_respects_per_gmail_account_daily_limit(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_INITIAL_CLAIMS_ENABLED", "true")
    monkeypatch.setenv("AUTOPILOT_DAILY_SEND_LIMIT", "50")
    monkeypatch.setenv("AUTOPILOT_PER_GMAIL_ACCOUNT_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    restaurant = create_restaurant(client)
    old_order = create_ready_order(client, restaurant["id"], "AUTO-OLD-SENT")
    create_ready_order(client, restaurant["id"], "AUTO-GMAIL-LIMIT")
    account = add_gmail_account(db_session)
    old_order_model = db_session.get(ClaimOrder, old_order["order_id"])
    assert old_order_model is not None
    old_order_model.status = "sent"
    existing_draft = EmailDraft(
        order_id=old_order["order_id"],
        draft_type="initial_claim",
        subject="Existing sent draft",
        body="Already sent today.",
        status="created",
    )
    db_session.add(existing_draft)
    db_session.flush()
    db_session.add(
        EmailProviderDraft(
            email_draft_id=existing_draft.id,
            email_account_id=account.id,
            provider="gmail",
            provider_draft_id="already-sent-today",
            provider_thread_id="thread-already-sent",
            provider_message_id="message-already-sent",
            to_email="restaurantsfrance@uber.com",
            subject=existing_draft.subject,
            status="sent",
            created_by_user_id=1,
            sent_by_user_id=1,
            sent_at=utc_now(),
        )
    )
    db_session.commit()

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "gmail_account_daily_limit_reached"
    sent_drafts = db_session.scalars(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")).all()
    assert len(sent_drafts) == 1
    get_settings.cache_clear()


def test_gmail_account_limit_uses_a_rolling_24_hour_window(
    client: TestClient,
    db_session: Session,
) -> None:
    restaurant = create_restaurant(client)
    order = create_ready_order(client, restaurant["id"], "AUTO-ROLLING-24H")
    account = add_gmail_account(db_session)
    for index, sent_at in enumerate(
        (
            utc_now() - timedelta(hours=23),
            utc_now() - timedelta(hours=25),
        ),
        start=1,
    ):
        draft = EmailDraft(
            order_id=order["order_id"],
            draft_type="initial_claim",
            subject=f"Rolling quota draft {index}",
            body="Already sent.",
            status="created",
        )
        db_session.add(draft)
        db_session.flush()
        db_session.add(
            EmailProviderDraft(
                email_draft_id=draft.id,
                email_account_id=account.id,
                provider="gmail",
                provider_draft_id=f"rolling-quota-draft-{index}",
                provider_thread_id=f"rolling-quota-thread-{index}",
                provider_message_id=f"rolling-quota-message-{index}",
                to_email="restaurantsfrance@uber.com",
                subject=draft.subject,
                status="sent",
                created_by_user_id=1,
                sent_by_user_id=1,
                sent_at=sent_at,
            )
        )
    db_session.commit()

    assert gmail_account_sent_last_24_hours_count(db_session, account.id) == 1
    assert gmail_account_send_pacing_active(db_session, account.id, 500) is False

    recent_draft = EmailDraft(
        order_id=order["order_id"],
        draft_type="initial_claim",
        subject="Recent paced draft",
        body="Just sent.",
        status="created",
    )
    db_session.add(recent_draft)
    db_session.flush()
    db_session.add(
        EmailProviderDraft(
            email_draft_id=recent_draft.id,
            email_account_id=account.id,
            provider="gmail",
            provider_draft_id="recent-paced-draft",
            provider_thread_id="recent-paced-thread",
            provider_message_id="recent-paced-message",
            to_email="restaurantsfrance@uber.com",
            subject=recent_draft.subject,
            status="sent",
            created_by_user_id=1,
            sent_by_user_id=1,
            sent_at=utc_now(),
        )
    )
    db_session.commit()

    assert gmail_account_send_pacing_active(db_session, account.id, 500) is True


def test_prepared_gmail_draft_is_resumed_once_then_respects_account_pacing(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "King Krousty")
    account = add_gmail_account(db_session)
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    provider_drafts: list[EmailProviderDraft] = []

    for index in range(2):
        ready = create_ready_order(client, restaurant["id"], f"QUEUE-{index + 1}")
        order = db_session.get(ClaimOrder, ready["order_id"])
        assert order is not None
        order.status = "refused"
        workflow = AppealWorkflow(
            case_type="claim_order",
            case_id=order.id,
            restaurant_id=order.restaurant_id,
            claim_order_id=order.id,
            status="appeal_needed",
            refusal_count=1,
            next_action_type="create_gmail_draft",
            next_action_at=utc_now() - timedelta(minutes=1),
            opened_by_user_id=owner.id,
        )
        db_session.add(workflow)
        db_session.flush()
        add_starred_inbound_message(db_session, order, account)
        draft = EmailDraft(
            order_id=order.id,
            draft_type="appeal_generic_refusal",
            subject=f"Re: commande {order.uber_order_number}",
            body=f"Relance commande {order.uber_order_number}.",
            status="created",
        )
        db_session.add(draft)
        db_session.flush()
        provider_draft = EmailProviderDraft(
            email_draft_id=draft.id,
            email_account_id=account.id,
            provider="gmail",
            provider_draft_id=f"queued-{order.uber_order_number}",
            provider_thread_id=f"thread-{order.uber_order_number}",
            to_email="restaurantsfrance@uber.com",
            subject=draft.subject,
            status="provider_draft_created",
            created_by_user_id=owner.id,
        )
        db_session.add(provider_draft)
        db_session.flush()
        db_session.add(
            AppealAttempt(
                workflow_id=workflow.id,
                attempt_number=1,
                appeal_type="first_appeal",
                status="gmail_draft_created",
                email_draft_id=draft.id,
                provider_draft_id=provider_draft.id,
                created_by_user_id=owner.id,
            )
        )
        provider_drafts.append(provider_draft)
        db_session.commit()

    first_result = resume_next_prepared_provider_draft(
        db_session,
        owner,
        account,
        fake_gmail_provider,
    )
    db_session.commit()
    second_result = resume_next_prepared_provider_draft(
        db_session,
        owner,
        account,
        fake_gmail_provider,
    )

    assert first_result.status == "sent"
    assert first_result.sent_count == 1
    assert second_result.status == "skipped"
    assert second_result.reason == "gmail_account_send_pacing_active"
    db_session.refresh(provider_drafts[0])
    db_session.refresh(provider_drafts[1])
    assert provider_drafts[0].status == "sent"
    assert provider_drafts[1].status == "provider_draft_created"
    assert fake_gmail_provider.sent_draft_ids == [provider_drafts[0].id]
    action = db_session.scalar(
        select(AutopilotAction).where(AutopilotAction.provider_draft_id == provider_drafts[0].id)
    )
    assert action is not None
    assert action.status == "sent"


def test_prepared_gmail_queue_skips_changed_thread_and_sends_next_safe_draft(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "King Krousty")
    account = add_gmail_account(db_session)
    owner = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert owner is not None
    queued: list[EmailProviderDraft] = []

    for index in range(2):
        ready = create_ready_order(client, restaurant["id"], f"THREAD-{index + 1}")
        order = db_session.get(ClaimOrder, ready["order_id"])
        assert order is not None
        order.status = "refused"
        workflow = AppealWorkflow(
            case_type="claim_order",
            case_id=order.id,
            restaurant_id=order.restaurant_id,
            claim_order_id=order.id,
            status="appeal_needed",
            refusal_count=1,
            next_action_type="create_gmail_draft",
            next_action_at=utc_now() - timedelta(minutes=1),
            opened_by_user_id=owner.id,
        )
        db_session.add(workflow)
        db_session.flush()
        add_starred_inbound_message(db_session, order, account)
        draft = EmailDraft(
            order_id=order.id,
            draft_type="appeal_generic_refusal",
            subject=f"Re: commande {order.uber_order_number}",
            body=f"Relance commande {order.uber_order_number}.",
            status="created",
        )
        db_session.add(draft)
        db_session.flush()
        thread_id = "thread-changed-after-draft" if index == 0 else f"thread-{order.uber_order_number}"
        provider_draft = EmailProviderDraft(
            email_draft_id=draft.id,
            email_account_id=account.id,
            provider="gmail",
            provider_draft_id=f"queued-thread-{order.uber_order_number}",
            provider_thread_id=thread_id,
            to_email="restaurantsfrance@uber.com",
            subject=draft.subject,
            status="provider_draft_created",
            created_by_user_id=owner.id,
        )
        db_session.add(provider_draft)
        db_session.flush()
        db_session.add(
            AppealAttempt(
                workflow_id=workflow.id,
                attempt_number=1,
                appeal_type="first_appeal",
                status="gmail_draft_created",
                email_draft_id=draft.id,
                provider_draft_id=provider_draft.id,
                created_by_user_id=owner.id,
            )
        )
        queued.append(provider_draft)
        db_session.commit()

    result = resume_next_prepared_provider_draft(
        db_session,
        owner,
        account,
        fake_gmail_provider,
    )

    assert result.status == "sent"
    assert result.provider_draft_id == queued[1].id
    db_session.refresh(queued[0])
    db_session.refresh(queued[1])
    assert queued[0].status == "provider_draft_created"
    assert queued[1].status == "sent"
    assert fake_gmail_provider.sent_draft_ids == [queued[1].id]


def test_autopilot_does_not_send_final_status(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-FINAL")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "accepted"
    db_session.commit()
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "all", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    assert response.json()["run"]["sent_count"] == 0


def test_autopilot_does_not_send_when_gmail_detected_positive_payment_signal(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-GMAIL-PAID")
    add_gmail_account(db_session)
    account = db_session.scalar(select(EmailAccount).where(EmailAccount.email_address == "owner@example.com"))
    assert account is not None
    message = InboundEmailMessage(
        email_account_id=account.id,
        order_id=ready["order_id"],
        provider="gmail",
        provider_message_id="positive-payment-signal",
        provider_thread_id="positive-payment-thread",
        from_email="restaurantsfrance@uber.com",
        subject="Paiement accorde",
        body_text="Nous confirmons une regularisation du paiement pour cette commande.",
        received_at=utc_now(),
        match_status="linked",
        match_reason="order_number_match",
        review_status="reviewed",
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        GmailResponseAnalysis(
            inbound_message_id=message.id,
            order_id=ready["order_id"],
            recommended_review_type="payment_to_verify",
            status="analyzed",
            confidence_score=Decimal("0.82"),
            reason="payment_signal",
        )
    )
    db_session.commit()

    response = client.post("/v1/autopilot/run", json={"mode": "initial_claims", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "positive_gmail_payment_signal_detected"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


@pytest.mark.parametrize(
    ("order_number", "payment_body"),
    [
        (
            "D461E",
            "Pour la commande D461E, nous avons decide de vous rembourser. "
            "Un montant de 59.96 EUR sera visible sur votre prochain paiement hebdomadaire.",
        ),
        (
            "E51E4",
            "Pour la commande E51E4, cette commande ne vous a pas ete reglee, mais compte tenu "
            "de la situation, je vais proceder a l'ajout du paiement pour cette commande, afin "
            "que vous soyez paye lors de votre prochain cycle de paiement.",
        ),
        (
            "60982",
            "Apres investigation, nous avons procede au remboursement du montant des plats "
            "signales manquants ou incorrects. Celui-ci apparait sous frais et autres paiements.",
        ),
    ],
)
def test_autopilot_preflight_blocks_appeal_when_older_thread_message_promised_payment(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
    order_number: str,
    payment_body: str,
) -> None:
    restaurant = create_restaurant(client, "Asian Passion")
    ready = create_ready_order(client, restaurant["id"], order_number)
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)
    starred_message = db_session.scalar(
        select(InboundEmailMessage).where(
            InboundEmailMessage.order_id == order.id,
            InboundEmailMessage.provider_message_id == f"starred-{order_number}",
        )
    )
    assert starred_message is not None
    existing_draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject=f"Re: Contestation commande {order_number}",
        body="Relance deja preparee.",
        status="created",
    )
    db_session.add(existing_draft)
    db_session.flush()
    existing_provider_draft = EmailProviderDraft(
        email_draft_id=existing_draft.id,
        email_account_id=account.id,
        provider="gmail",
        provider_draft_id=f"existing-provider-draft-{order_number}",
        provider_thread_id=f"thread-{order_number}",
        to_email="restaurantsfrance@uber.com",
        subject=existing_draft.subject,
        status="provider_draft_created",
        created_by_user_id=1,
    )
    db_session.add(existing_provider_draft)
    db_session.flush()
    db_session.add(
        AppealAttempt(
            workflow_id=workflow.id,
            attempt_number=1,
            appeal_type="first_appeal",
            status="gmail_draft_created",
            based_on_refusal_message_id=starred_message.id,
            email_draft_id=existing_draft.id,
            provider_draft_id=existing_provider_draft.id,
            created_by_user_id=1,
        )
    )
    db_session.commit()
    thread_id = f"thread-{order_number}"
    fake_gmail_provider.thread_payloads[thread_id] = [
        InboundEmailPayload(
            provider_message_id=f"remote-payment-{order_number}",
            provider_thread_id=thread_id,
            gmail_history_id=f"history-payment-{order_number}",
            from_email="restaurantsfrance@uber.com",
            to_email=account.email_address,
            subject=f"Re: Contestation commande {order_number}",
            snippet=payment_body,
            body_text=payment_body,
            received_at=utc_now() - timedelta(days=1),
            raw_headers={},
            provider_labels=["INBOX"],
        ),
        InboundEmailPayload(
            provider_message_id=f"remote-admin-{order_number}",
            provider_thread_id=thread_id,
            gmail_history_id=f"history-admin-{order_number}",
            from_email="restaurantsfrance@uber.com",
            to_email=account.email_address,
            subject=f"Re: Contestation commande {order_number}",
            snippet="Votre demande a ete transmise.",
            body_text="Votre demande a ete transmise a l'equipe competente.",
            received_at=utc_now(),
            raw_headers={},
            provider_labels=["INBOX", "STARRED"],
        ),
    ]

    response = client.post(
        "/v1/autopilot/run",
        json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "positive_gmail_thread_history_detected"
    assert fake_gmail_provider.sent_draft_ids == []
    db_session.refresh(existing_provider_draft)
    assert existing_provider_draft.status == "provider_draft_created"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_followup_skips_when_payment_review_exists(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-REVIEW-PAID")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "sent"
    order.first_email_sent_at = utc_now() - timedelta(days=5)
    task = FollowUpTask(order_id=order.id, task_type="followup_1", status="pending", due_at=utc_now() - timedelta(hours=1))
    db_session.add(task)
    db_session.add(
        ClaimResponseReview(
            order_id=order.id,
            reviewed_by_user_id=1,
            review_type="payment_confirmed",
            previous_order_status="sent",
            new_order_status="payment_confirmed",
            recovered_amount=order.order_amount,
            notes="Paiement confirme par Uber.",
        )
    )
    db_session.commit()
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "followups", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "positive_payment_review_exists"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_followup_respects_cooldown(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-FOLLOW")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "sent"
    order.first_email_sent_at = utc_now() - timedelta(days=5)
    order.last_followup_sent_at = utc_now() - timedelta(hours=1)
    task = FollowUpTask(order_id=order.id, task_type="followup_1", status="pending", due_at=utc_now() - timedelta(hours=1))
    db_session.add(task)
    db_session.commit()
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "followups", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    assert response.json()["actions"][0]["skipped_reason"] == "cooldown_active"


def test_autopilot_followup_requires_complete_restaurant_signature(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    restaurant_record = db_session.get(Restaurant, restaurant["id"])
    assert restaurant_record is not None
    restaurant_record.phone_number = None
    db_session.commit()
    ready = create_ready_order(client, restaurant["id"], "AUTO-FOLLOW-NO-SIGNATURE")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "sent"
    order.first_email_sent_at = utc_now() - timedelta(days=5)
    task = FollowUpTask(order_id=order.id, task_type="followup_1", status="pending", due_at=utc_now() - timedelta(hours=1))
    db_session.add(task)
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)
    db_session.commit()

    response = client.post("/v1/autopilot/run", json={"mode": "followups", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "missing_restaurant_phone_number"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_followup_blocks_internal_brand_in_restaurant_signature(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, name="Restaurant Test TENNET")
    ready = create_ready_order(client, restaurant["id"], "AUTO-FOLLOW-BRAND")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "sent"
    order.first_email_sent_at = utc_now() - timedelta(days=5)
    task = FollowUpTask(order_id=order.id, task_type="followup_1", status="pending", due_at=utc_now() - timedelta(hours=1))
    db_session.add(task)
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)
    db_session.commit()

    response = client.post("/v1/autopilot/run", json={"mode": "followups", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "restaurant_signature_contains_internal_brand"
    assert db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.status == "sent")) is None


def test_autopilot_appeal_after_refusal_does_not_close(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-APPEAL")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    db_session.refresh(workflow)
    assert workflow.status != "manually_closed"
    assert workflow.appeal_attempt_count == 1


def test_autopilot_replies_to_starred_thread_without_customer_or_date(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "Frit Dodo")
    ready = create_ready_order(client, restaurant["id"], "F93BA")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.customer_name = None
    order.order_date = None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 1
    assert payload["actions"][0]["skipped_reason"] is None
    draft = db_session.scalar(select(EmailDraft).where(EmailDraft.order_id == order.id).order_by(EmailDraft.id.desc()))
    assert draft is not None
    assert "TENNET" not in draft.body
    assert "F93BA" in draft.body
    assert "Frit Dodo" in draft.body
    assert "108 Avenue du Marechal Foch" in draft.body
    assert "0605807385" in draft.body
    assert "Historique" not in draft.body
    provider_draft = db_session.scalar(select(EmailProviderDraft).where(EmailProviderDraft.email_draft_id == draft.id))
    assert provider_draft is not None
    assert provider_draft.status == "sent"


def test_autopilot_replies_to_starred_thread_without_amount(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "Frit Dodo")
    ready = create_ready_order(client, restaurant["id"], "BAEF7")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.order_amount = None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 1
    assert payload["actions"][0]["skipped_reason"] is None
    draft = db_session.scalar(select(EmailDraft).where(EmailDraft.order_id == order.id).order_by(EmailDraft.id.desc()))
    assert draft is not None
    assert "BAEF7" in draft.body
    assert "Frit Dodo" in draft.body
    assert "Montant concerne : 0.00" not in draft.body
    assert "TENNET" not in draft.body


def test_autopilot_replies_to_new_starred_response_even_when_cooldown_active(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "Frit Dodo")
    ready = create_ready_order(client, restaurant["id"], "STAR-NEW-REFUSAL")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "refused"
    last_sent_at = utc_now() - timedelta(minutes=10)
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=2,
        appeal_attempt_count=1,
        last_appeal_sent_at=last_sent_at,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(minutes=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account, received_at=last_sent_at + timedelta(minutes=5))

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 1
    assert payload["actions"][0]["skipped_reason"] is None
    db_session.refresh(workflow)
    assert workflow.appeal_attempt_count == 2


def test_autopilot_appeal_requires_starred_gmail_thread(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-APPEAL-NOT-STARRED")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "starred_gmail_thread_required"


def test_autopilot_blocks_appeal_linked_to_another_order_thread(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "King Krousty")
    ready = create_ready_order(client, restaurant["id"], "ABCDE")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    order.status = "refused"
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    thread_id = "thread-original-order-5cadf"
    db_session.add_all(
        [
            InboundEmailMessage(
                email_account_id=account.id,
                order_id=order.id,
                provider="gmail",
                provider_message_id="sent-original-5cadf",
                provider_thread_id=thread_id,
                from_email=account.email_address,
                to_email="restaurantsfrance@uber.com",
                subject="Contestation commande Uber Eats 5CADF",
                body_text="Je conteste la commande numero 5CADF pour Tacos Master.",
                provider_labels_json=["SENT"],
                match_status="linked",
                match_reason="thread_id_match",
                review_status="reviewed",
                received_at=utc_now() - timedelta(days=2),
            ),
            InboundEmailMessage(
                email_account_id=account.id,
                order_id=order.id,
                provider="gmail",
                provider_message_id="starred-refusal-wrong-order",
                provider_thread_id=thread_id,
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Re: Contestation commande Uber Eats 5CADF",
                body_text="Votre demande est refusee.",
                provider_labels_json=["INBOX", "STARRED"],
                match_status="linked",
                match_reason="thread_id_match",
                review_status="reviewed",
                received_at=utc_now() - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        "/v1/autopilot/dry-run",
        json={"mode": "appeals", "restaurant_id": restaurant["id"]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["run"]["sent_count"] == 0
    assert payload["actions"][0]["skipped_reason"] == "gmail_thread_order_identity_mismatch"
    assert fake_gmail_provider.sent_draft_ids == []


def test_autopilot_repairs_missing_identity_from_starred_gmail_thread(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "Frit Dodo")
    order = ClaimOrder(
        restaurant_id=restaurant["id"],
        uber_order_number="AUTO-IDENTITY-MISSING",
        customer_name=None,
        order_date=None,
        order_amount=Decimal("24.99"),
        currency="EUR",
        accepted_by_restaurant=True,
        prepared_before_cancellation=True,
        status="refused",
    )
    db_session.add(order)
    db_session.flush()
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_identity_message(db_session, order, account)

    response = client.post("/v1/autopilot/dry-run", json={"mode": "appeals", "restaurant_id": restaurant["id"]})

    assert response.status_code == 201
    payload = response.json()
    assert payload["actions"][0]["reason"] == "dry_run_candidate"
    assert payload["actions"][0]["skipped_reason"] is None
    db_session.refresh(order)
    assert order.customer_name == "Yoann O"
    assert order.order_date is not None
    assert order.order_date.isoformat() == "2026-06-18"
    assert order.internal_reference == "F93BA"


def test_autopilot_reopens_manual_review_when_starred_gmail_thread_has_complete_identity(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client, "Frit Dodo")
    order = ClaimOrder(
        restaurant_id=restaurant["id"],
        uber_order_number="AUTO-MANUAL-REPAIR",
        customer_name=None,
        order_date=None,
        order_amount=Decimal("24.99"),
        currency="EUR",
        accepted_by_restaurant=True,
        prepared_before_cancellation=True,
        status="refused",
    )
    db_session.add(order)
    db_session.flush()
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="manual_review",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.flush()
    db_session.add(
        RefusalAnalysis(
            workflow_id=workflow.id,
            refusal_source="manual",
            refusal_reason="generic_refusal",
            refusal_text_excerpt="Uber semble refuser la demande.",
            recommended_next_action="manual_review",
            required_evidence_types_json=[],
            confidence=Decimal("0.50"),
        )
    )
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_identity_message(db_session, order, account)

    response = client.post("/v1/autopilot/dry-run", json={"mode": "appeals", "restaurant_id": restaurant["id"]})

    assert response.status_code == 201
    payload = response.json()
    assert payload["actions"][0]["action_type"] == "send_appeal"
    assert payload["actions"][0]["skipped_reason"] is None
    db_session.refresh(workflow)
    assert workflow.next_action_type == "review_refusal"


def test_autopilot_repairs_identity_from_attached_proof_image_when_gmail_text_is_incomplete(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("EVIDENCE_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()

    monkeypatch.setattr(
        OpenAIStructuredAnalysisService,
        "analyze_order_identity_text",
        lambda *args, **kwargs: None,
    )

    def fake_analyze_proof(self, **kwargs) -> AIProofExtraction:
        return AIProofExtraction(
            detected_evidence_type="ticket_agraphe",
            case_type="refund",
            restaurant_name="Frit Dodo",
            customer_name="Yoann O",
            order_number="F93BA",
            display_id="F93BA",
            order_date=None,
            order_amount=Decimal("24.99"),
            currency="EUR",
            confidence=Decimal("0.92"),
            missing_fields=["order_date"],
            notes="ticket visible",
        )

    monkeypatch.setattr(OpenAIStructuredAnalysisService, "analyze_proof", fake_analyze_proof)

    restaurant = create_restaurant(client, "Frit Dodo")
    order = ClaimOrder(
        restaurant_id=restaurant["id"],
        uber_order_number="AUTO-PROOF-IDENTITY",
        customer_name=None,
        order_date=date(2026, 6, 18),
        order_amount=Decimal("24.99"),
        currency="EUR",
        accepted_by_restaurant=True,
        prepared_before_cancellation=True,
        status="refused",
    )
    db_session.add(order)
    db_session.flush()
    relative_path = Path(f"restaurant_{order.restaurant_id}") / f"order_{order.id}" / "proof.jpg"
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake-image-bytes")
    db_session.add(
        EvidenceFile(
            order_id=order.id,
            evidence_type="preparation_proof",
            original_filename="preuve-ticket-agraphe.jpg",
            storage_path=relative_path.as_posix(),
            storage_backend="local",
            mime_type="image/jpeg",
            file_size=target.stat().st_size,
        )
    )
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.commit()
    account = add_gmail_account(db_session)
    add_starred_inbound_message(db_session, order, account)

    response = client.post("/v1/autopilot/dry-run", json={"mode": "appeals", "restaurant_id": restaurant["id"]})

    assert response.status_code == 201
    payload = response.json()
    assert payload["actions"][0]["reason"] == "dry_run_candidate"
    assert payload["actions"][0]["skipped_reason"] is None
    db_session.refresh(order)
    assert order.customer_name == "Yoann O"
    assert order.internal_reference == "F93BA"


def test_autopilot_appeal_refuses_same_template_without_new_argument(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    restaurant = create_restaurant(client)
    ready = create_ready_order(client, restaurant["id"], "AUTO-SAME")
    order = db_session.get(ClaimOrder, ready["order_id"])
    assert order is not None
    workflow = AppealWorkflow(
        case_type="claim_order",
        case_id=order.id,
        restaurant_id=order.restaurant_id,
        claim_order_id=order.id,
        status="appeal_needed",
        refusal_count=1,
        appeal_attempt_count=1,
        last_appeal_sent_at=utc_now() - timedelta(days=3),
        next_action_type="create_appeal_draft",
        next_action_at=utc_now() - timedelta(hours=1),
    )
    db_session.add(workflow)
    db_session.flush()
    draft = EmailDraft(
        order_id=order.id,
        draft_type="appeal_generic_refusal",
        subject="Appeal",
        body="Appeal body",
        status="created",
    )
    db_session.add(draft)
    db_session.flush()
    db_session.add(
        AppealAttempt(
            workflow_id=workflow.id,
            attempt_number=1,
            appeal_type="first_appeal",
            status="sent",
            email_draft_id=draft.id,
            new_evidence_summary="",
            created_by_user_id=1,
            sent_by_user_id=1,
            sent_at=utc_now() - timedelta(days=3),
            completed_at=utc_now() - timedelta(days=3),
        )
    )
    db_session.commit()
    add_gmail_account(db_session)

    response = client.post("/v1/autopilot/run", json={"mode": "appeals", "restaurant_id": restaurant["id"], "dry_run": False})

    assert response.status_code == 201
    assert response.json()["actions"][0]["skipped_reason"] == "same_template_without_new_argument"


def test_autopilot_emergency_stop_blocks_run(
    client: TestClient,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    stop_response = client.post("/v1/autopilot/stop")
    assert stop_response.status_code == 201

    response = client.post("/v1/autopilot/run", json={"mode": "all", "dry_run": False})

    assert response.status_code == 409
    assert response.json()["detail"] == "autopilot_emergency_stopped"


def test_autopilot_emergency_resume_releases_stop(
    client: TestClient,
    db_session: Session,
    fake_gmail_provider: FakeAutopilotGmailProvider,
    autopilot_enabled: None,
) -> None:
    stop_response = client.post("/v1/autopilot/stop")
    assert stop_response.status_code == 201

    resume_response = client.post("/v1/autopilot/resume")
    assert resume_response.status_code == 201
    assert resume_response.json()["mode"] == "emergency_stop"
    assert resume_response.json()["status"] == "completed"

    status_response = client.get("/v1/autopilot/status")
    assert status_response.status_code == 200
    assert status_response.json()["emergency_stopped"] is False
    assert (
        db_session.scalar(
            select(AuditLog).where(AuditLog.action == "autopilot.emergency_resumed")
        )
        is not None
    )
