from __future__ import annotations

from collections.abc import Generator
from datetime import date, timedelta
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
from app.services.email_provider import EmailConnectionStatus, EmailSendResult


class FakeAutopilotGmailProvider:
    provider = "gmail"

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
        provider_draft = EmailProviderDraft(
            email_draft_id=email_draft.id,
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
        return EmailSendResult(
            provider_message_id=f"fake-message-{provider_draft.id}",
            provider_thread_id=provider_draft.provider_thread_id or f"fake-thread-{provider_draft.id}",
            sent_at=utc_now(),
        )


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


def add_starred_inbound_message(db_session: Session, order: ClaimOrder, account: EmailAccount) -> None:
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
            received_at=utc_now(),
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
