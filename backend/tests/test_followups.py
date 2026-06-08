from collections.abc import Generator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import app
from app.models import AuditLog, ClaimOrder, EmailAccount, EmailDraft, EmailProviderDraft, EmailThread, FollowUpTask, User
from app.models.domain import utc_now
from app.routes.email import get_gmail_provider
from app.services.email_provider import EmailConnectionStatus


class FakeGmailEmailProvider:
    provider = "gmail"

    def get_connection_status(self, db: Session, user: User) -> EmailConnectionStatus:
        if not get_settings().email_provider_enabled:
            return EmailConnectionStatus(connected=False, provider=self.provider, email_address=None, enabled=False)
        account = get_active_account(db, user.id)
        return EmailConnectionStatus(
            connected=account is not None,
            provider=self.provider,
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
            provider_draft_id=f"fake-followup-draft-{email_draft.id}",
            provider_thread_id=f"fake-followup-thread-{email_draft.id}",
            to_email=to_email,
            subject=email_draft.subject,
            status="provider_draft_created",
            created_by_user_id=user.id,
        )
        db.add(provider_draft)
        db.flush()
        return provider_draft


@pytest.fixture()
def gmail_enabled(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("EMAIL_PROVIDER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_SECRET", "test-client-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_gmail_provider() -> Generator[FakeGmailEmailProvider, None, None]:
    provider = FakeGmailEmailProvider()
    app.dependency_overrides[get_gmail_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_gmail_provider, None)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_restaurant(client: TestClient, name: str = "Followup Restaurant") -> dict:
    response = client.post("/v1/restaurants", json={"name": name, "sender_email": "claims@example.com"})
    assert response.status_code == 201
    return response.json()


def create_user(client: TestClient, email: str, role: str) -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "user-password",
            "full_name": f"{role.title()} Test",
            "role": role,
            "active": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def assign_restaurant(client: TestClient, user_id: int, restaurant_id: int) -> None:
    response = client.post(f"/v1/users/{user_id}/restaurants", json={"restaurant_id": restaurant_id})
    assert response.status_code == 201


def login(client: TestClient, email: str, password: str = "user-password") -> str:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def create_order(client: TestClient, restaurant_id: int, order_number: str) -> dict:
    response = client.post(
        "/v1/orders",
        json={
            "restaurant_id": restaurant_id,
            "uber_order_number": order_number,
            "order_amount": "24.90",
            "currency": "EUR",
            "accepted_by_restaurant": True,
            "prepared_before_cancellation": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def add_evidence(client: TestClient, order_id: int, evidence_type: str) -> None:
    response = client.post(
        f"/v1/orders/{order_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "original_filename": f"{evidence_type}.png",
            "storage_path": f"storage/evidence/{evidence_type}.png",
            "mime_type": "image/png",
            "file_size": 1024,
        },
    )
    assert response.status_code == 201


def create_sent_order(
    client: TestClient,
    db_session: Session,
    restaurant_id: int,
    order_number: str,
    *,
    sent_days_ago: int,
    status: str = "sent",
) -> ClaimOrder:
    order_data = create_order(client, restaurant_id, order_number)
    add_evidence(client, order_data["id"], "cancellation_proof")
    add_evidence(client, order_data["id"], "preparation_proof")
    validate_response = client.post(f"/v1/orders/{order_data['id']}/validate")
    assert validate_response.status_code == 200
    draft_response = client.post(f"/v1/orders/{order_data['id']}/drafts", json={"draft_type": "initial_claim"})
    assert draft_response.status_code == 201

    sent_at = utc_now() - timedelta(days=sent_days_ago)
    order = db_session.get(ClaimOrder, order_data["id"])
    assert order is not None
    order.status = status
    order.first_email_sent_at = sent_at
    order.updated_at = sent_at
    draft = db_session.get(EmailDraft, draft_response.json()["id"])
    assert draft is not None
    db_session.add(
        EmailProviderDraft(
            email_draft_id=draft.id,
            provider="gmail",
            provider_draft_id=f"sent-initial-{order.id}",
            provider_thread_id=f"thread-{order.id}",
            provider_message_id=f"message-{order.id}",
            to_email="merchants@uber.com",
            subject=draft.subject,
            status="sent",
            created_by_user_id=1,
            sent_by_user_id=1,
            sent_at=sent_at,
        )
    )
    db_session.add(
        EmailThread(
            order_id=order.id,
            provider="gmail",
            thread_id=f"thread-{order.id}",
            message_id=f"message-{order.id}",
            direction="outbound",
            subject=draft.subject,
            body=draft.body,
            sent_at=sent_at,
        )
    )
    db_session.commit()
    db_session.refresh(order)
    return order


def add_followup_draft(db_session: Session, order_id: int, draft_type: str) -> EmailDraft:
    order = db_session.get(ClaimOrder, order_id)
    assert order is not None
    draft = EmailDraft(
        order_id=order_id,
        draft_type=draft_type,
        subject=f"{draft_type} {order.uber_order_number}",
        body="Follow-up body",
        status="created",
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)
    return draft


def get_owner(db_session: Session) -> User:
    user = db_session.scalar(select(User).where(User.email == "owner@example.com"))
    assert user is not None
    return user


def get_active_account(db: Session, user_id: int) -> EmailAccount | None:
    return db.scalar(
        select(EmailAccount).where(
            EmailAccount.user_id == user_id,
            EmailAccount.provider == "gmail",
            EmailAccount.disconnected_at.is_(None),
        )
    )


def connect_gmail_account(db_session: Session, user_id: int) -> None:
    db_session.add(
        EmailAccount(
            user_id=user_id,
            provider="gmail",
            email_address="connected@example.com",
            access_token_encrypted="encrypted-access-token",
            refresh_token_encrypted="encrypted-refresh-token",
            scopes="https://www.googleapis.com/auth/gmail.compose",
        )
    )
    db_session.commit()


def recalculate(client: TestClient, token: str | None = None) -> dict:
    response = client.post("/v1/followups/recalculate", json={}, headers=auth_headers(token) if token else None)
    assert response.status_code == 200
    return response.json()


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_recalculate_creates_followup_1_due_for_old_sent_order(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-1", sent_days_ago=3)

    result = recalculate(client)

    assert result["created_tasks"] == 1
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert task.task_type == "followup_1"
    assert task.status == "pending"


def test_recalculate_creates_followup_2_when_followup_1_exists(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-2", sent_days_ago=6)
    add_followup_draft(db_session, order.id, "followup_1")

    recalculate(client)

    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert task.task_type == "followup_2"


def test_recalculate_creates_escalation_when_two_followups_exist(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-ESC", sent_days_ago=11)
    add_followup_draft(db_session, order.id, "followup_1")
    add_followup_draft(db_session, order.id, "followup_2")

    recalculate(client)

    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert task.task_type == "escalation"


def test_recalculate_creates_manual_review_after_day_15(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-MANUAL", sent_days_ago=16)

    result = recalculate(client)

    assert result["manual_review_orders"] == 1
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert task.task_type == "manual_review"


@pytest.mark.parametrize("final_status", ["accepted", "payment_confirmed", "refused", "closed"])
def test_no_followup_created_for_final_statuses(client: TestClient, db_session: Session, final_status: str) -> None:
    restaurant = create_restaurant(client)
    create_sent_order(client, db_session, restaurant["id"], f"UBER-FU-FINAL-{final_status}", sent_days_ago=16, status=final_status)

    result = recalculate(client)

    assert result["created_tasks"] == 0
    assert db_session.scalar(select(FollowUpTask.id)) is None


def test_recalculate_does_not_create_duplicate_task(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    create_sent_order(client, db_session, restaurant["id"], "UBER-FU-DUP", sent_days_ago=3)

    assert recalculate(client)["created_tasks"] == 1
    assert recalculate(client)["created_tasks"] == 0
    assert len(db_session.scalars(select(FollowUpTask)).all()) == 1


def test_manager_assigned_can_see_followups(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    create_sent_order(client, db_session, restaurant["id"], "UBER-FU-MGR", sent_days_ago=3)
    recalculate(client)
    manager = create_user(client, "manager-followups@example.com", "manager")
    assign_restaurant(client, manager["id"], restaurant["id"])
    manager_token = login(client, "manager-followups@example.com")

    response = client.get("/v1/followups/due", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert len(response.json()["tasks"]) == 1


def test_manager_non_assigned_does_not_see_followups(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    create_sent_order(client, db_session, restaurant["id"], "UBER-FU-NOMGR", sent_days_ago=3)
    recalculate(client)
    manager = create_user(client, "manager-no-followups@example.com", "manager")
    other_restaurant = create_restaurant(client, "Other Restaurant")
    assign_restaurant(client, manager["id"], other_restaurant["id"])
    manager_token = login(client, "manager-no-followups@example.com")

    response = client.get("/v1/followups/due", headers=auth_headers(manager_token))

    assert response.status_code == 200
    assert response.json()["tasks"] == []


def test_staff_cannot_recalculate(client: TestClient) -> None:
    staff = create_user(client, "staff-followups@example.com", "staff")
    staff_token = login(client, staff["email"])

    response = client.post("/v1/followups/recalculate", json={}, headers=auth_headers(staff_token))

    assert response.status_code == 403


def test_create_draft_creates_followup_email_draft(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-DRAFT", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None

    response = client.post(f"/v1/followups/{task.id}/create-draft")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "draft_created"
    assert data["generated_email_draft_id"] is not None
    draft = db_session.get(EmailDraft, data["generated_email_draft_id"])
    assert draft is not None
    assert draft.draft_type == "followup_1"


def test_create_draft_refuses_non_pending_task(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-DRAFT-BLOCK", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert client.post(f"/v1/followups/{task.id}/create-draft").status_code == 200

    response = client.post(f"/v1/followups/{task.id}/create-draft")

    assert response.status_code == 409


def test_create_gmail_draft_creates_provider_draft_without_sending(
    client: TestClient,
    db_session: Session,
    gmail_enabled: None,
    fake_gmail_provider: FakeGmailEmailProvider,
) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-GMAIL", sent_days_ago=3)
    connect_gmail_account(db_session, get_owner(db_session).id)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert client.post(f"/v1/followups/{task.id}/create-draft").status_code == 200

    response = client.post(f"/v1/followups/{task.id}/create-gmail-draft")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "provider_draft_created"
    provider_draft = db_session.get(EmailProviderDraft, data["generated_provider_draft_id"])
    assert provider_draft is not None
    assert provider_draft.status == "provider_draft_created"
    assert provider_draft.sent_at is None


def test_skip_sets_status_skipped(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-SKIP", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None

    response = client.post(f"/v1/followups/{task.id}/skip", json={"skip_reason": "Deja traite manuellement"})

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert db_session.scalar(select(AuditLog.id).where(AuditLog.action == "followup_task.skipped")) is not None


def test_complete_sets_status_completed(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-COMPLETE", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None

    response = client.post(f"/v1/followups/{task.id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_complete_after_sent_provider_draft_increments_retry_count(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-SENT-COMPLETE", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    draft = add_followup_draft(db_session, order.id, "followup_1")
    provider_draft = EmailProviderDraft(
        email_draft_id=draft.id,
        provider="gmail",
        provider_draft_id=f"sent-followup-{order.id}",
        provider_thread_id=f"sent-followup-thread-{order.id}",
        provider_message_id=f"sent-followup-message-{order.id}",
        to_email="merchants@uber.com",
        subject=draft.subject,
        status="sent",
        created_by_user_id=1,
        sent_by_user_id=1,
        sent_at=utc_now(),
    )
    db_session.add(provider_draft)
    db_session.flush()
    task.generated_email_draft_id = draft.id
    task.generated_provider_draft_id = provider_draft.id
    task.status = "provider_draft_created"
    db_session.commit()

    response = client.post(f"/v1/followups/{task.id}/complete")

    assert response.status_code == 200
    db_session.refresh(order)
    assert order.retry_count == 1
    assert order.status == "followup_1_sent"
    assert order.last_followup_sent_at is not None


def test_dashboard_summary_includes_followup_counters(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    create_sent_order(client, db_session, restaurant["id"], "UBER-FU-DASH", sent_days_ago=3)
    recalculate(client)

    response = client.get("/v1/dashboard/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["followups_due_count"] >= 1
    assert data["followups_pending_count"] >= 1
    assert "escalations_due_count" in data
    assert "manual_review_due_count" in data


def test_audit_log_created_for_recalculate_create_skip_complete(client: TestClient, db_session: Session) -> None:
    restaurant = create_restaurant(client)
    order = create_sent_order(client, db_session, restaurant["id"], "UBER-FU-AUDIT", sent_days_ago=3)
    recalculate(client)
    task = db_session.scalar(select(FollowUpTask).where(FollowUpTask.order_id == order.id))
    assert task is not None
    assert client.post(f"/v1/followups/{task.id}/create-draft").status_code == 200
    assert client.post(f"/v1/followups/{task.id}/complete").status_code == 200

    actions = set(db_session.scalars(select(AuditLog.action)).all())

    assert "followup_task.recalculate" in actions
    assert "followup_task.recalculate_created" in actions
    assert "followup_task.email_draft_created" in actions
    assert "followup_task.completed" in actions
