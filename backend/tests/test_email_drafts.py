from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


FORBIDDEN_UBER_VISIBLE_TERMS = [
    "TENNET",
    "Historique",
    "Mots cles",
    "generic_refusal",
    "dispute_type",
    "Raison detectee",
    "Extrait / notes",
]


def assert_clean_uber_email(subject: str, body: str) -> None:
    combined = f"{subject}\n{body}"
    for term in FORBIDDEN_UBER_VISIBLE_TERMS:
        assert term not in combined


def create_restaurant(client: TestClient, name: str = "Restaurant Email") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={
            "name": name,
            "sender_email": "claims@example.com",
        },
    )
    assert response.status_code == 201
    return response.json()


def order_payload(
    restaurant_id: int,
    uber_order_number: str = "UBER-DRAFT-1",
    include_optional: bool = True,
) -> dict:
    payload = {
        "restaurant_id": restaurant_id,
        "uber_order_number": uber_order_number,
        "order_amount": "32.40",
        "currency": "EUR",
        "accepted_by_restaurant": True,
        "prepared_before_cancellation": True,
    }
    if include_optional:
        payload.update(
            {
                "customer_name": "Client Email",
                "order_date": "2026-06-07",
                "loss_type": "prepared_cancelled_order",
            }
        )
    return payload


def create_order(
    client: TestClient,
    restaurant_id: int,
    uber_order_number: str = "UBER-DRAFT-1",
    include_optional: bool = True,
) -> dict:
    response = client.post(
        "/v1/orders",
        json=order_payload(restaurant_id, uber_order_number, include_optional),
    )
    assert response.status_code == 201
    return response.json()


def add_evidence(client: TestClient, order_id: int, evidence_type: str) -> dict:
    response = client.post(
        f"/v1/orders/{order_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "original_filename": f"{evidence_type}.png",
            "storage_path": f"storage/evidence/{evidence_type}.png",
            "mime_type": "image/png",
            "file_size": 2048,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_ready_order(
    client: TestClient,
    restaurant_name: str = "Restaurant Email",
    uber_order_number: str = "UBER-DRAFT-1",
    include_optional: bool = True,
) -> tuple[dict, dict]:
    restaurant = create_restaurant(client, restaurant_name)
    order = create_order(client, restaurant["id"], uber_order_number, include_optional)
    add_evidence(client, order["id"], "cancellation_proof")
    add_evidence(client, order["id"], "preparation_proof")
    response = client.post(f"/v1/orders/{order['id']}/validate")
    assert response.status_code == 200
    assert response.json()["new_status"] == "ready_to_send"
    return restaurant, order


def create_initial_claim_draft(client: TestClient, order_id: int) -> dict:
    response = client.post(f"/v1/orders/{order_id}/drafts", json={"draft_type": "initial_claim"})
    assert response.status_code == 201
    return response.json()


def test_health_still_works(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_initial_claim_created_for_ready_complete_order(client: TestClient) -> None:
    _, order = create_ready_order(client)

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})

    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == order["id"]
    assert data["draft_type"] == "initial_claim"
    assert data["status"] == "created"


def test_initial_claim_rejected_if_missing_evidence(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"], "UBER-MISSING-EVIDENCE")
    response = client.post(f"/v1/orders/{order['id']}/validate")
    assert response.status_code == 200
    assert response.json()["new_status"] == "missing_evidence"

    draft_response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})

    assert draft_response.status_code == 409


def test_initial_claim_rejected_if_order_is_draft(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"], "UBER-STILL-DRAFT")

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})

    assert response.status_code == 409


def test_initial_claim_rejected_if_order_is_accepted(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-ACCEPTED")
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "accepted"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})

    assert response.status_code == 409
    assert client.get(f"/v1/orders/{order['id']}").json()["status"] == "accepted"


def test_initial_claim_rejected_if_order_is_payment_confirmed(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-PAID")
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "payment_confirmed"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "initial_claim"})

    assert response.status_code == 409
    assert client.get(f"/v1/orders/{order['id']}").json()["status"] == "payment_confirmed"


def test_initial_claim_body_contains_required_claim_data(client: TestClient) -> None:
    restaurant, order = create_ready_order(
        client,
        restaurant_name="Restaurant Claims",
        uber_order_number="UBER-CONTENT",
    )

    draft = create_initial_claim_draft(client, order["id"])

    assert "UBER-CONTENT" in draft["body"]
    assert "commande Uber Eats de Client Email, numero de commande UBER-CONTENT, du 07/06/2026" in draft["body"]
    assert restaurant["name"] in draft["body"]
    assert "32.40 EUR" in draft["body"]
    assert "cancellation_proof.png" in draft["body"]
    assert "preparation_proof.png" in draft["body"]
    assert_clean_uber_email(draft["subject"], draft["body"])
    assert draft["subject"] == "Contestation d'annulation de commande - UBER-CONTENT"


def test_initial_claim_does_not_invent_optional_missing_data(client: TestClient) -> None:
    _, order = create_ready_order(
        client,
        restaurant_name="Restaurant Minimal",
        uber_order_number="UBER-NO-OPTIONAL",
        include_optional=False,
    )

    draft = create_initial_claim_draft(client, order["id"])

    assert "Client :" not in draft["body"]
    assert "Date de commande :" not in draft["body"]
    assert "Type de perte :" not in draft["body"]


def test_order_status_becomes_draft_email_created_after_initial_claim(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-STATUS")

    create_initial_claim_draft(client, order["id"])

    response = client.get(f"/v1/orders/{order['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "draft_email_created"


def test_audit_log_created_after_initial_claim(
    client: TestClient,
    db_session: Session,
) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-AUDIT")

    draft = create_initial_claim_draft(client, order["id"])

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "email_draft",
            AuditLog.entity_id == draft["id"],
            AuditLog.action == "create_email_draft",
        )
    )
    assert audit_log is not None
    assert '"draft_type": "initial_claim"' in (audit_log.new_value or "")


def test_followup_1_rejected_if_initial_claim_draft_is_missing(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"], "UBER-FOLLOWUP-NO-INITIAL")
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "sent"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "followup_1"})

    assert response.status_code == 409


def test_followup_1_created_if_initial_claim_exists(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-FOLLOWUP-1")
    create_initial_claim_draft(client, order["id"])

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "followup_1"})

    assert response.status_code == 201
    assert response.json()["draft_type"] == "followup_1"


def test_followup_2_rejected_if_followup_1_is_missing(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-FOLLOWUP-2")
    create_initial_claim_draft(client, order["id"])

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "followup_2"})

    assert response.status_code == 409


def test_escalation_rejected_on_final_status(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-ESCALATION")
    create_initial_claim_draft(client, order["id"])
    patch_response = client.patch(f"/v1/orders/{order['id']}", json={"status": "accepted"})
    assert patch_response.status_code == 200

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "escalation"})

    assert response.status_code == 409


def test_proof_reply_created_if_evidence_exists(client: TestClient) -> None:
    restaurant = create_restaurant(client)
    order = create_order(client, restaurant["id"], "UBER-PROOF-REPLY")
    add_evidence(client, order["id"], "receipt")

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "proof_reply"})

    assert response.status_code == 201
    assert response.json()["draft_type"] == "proof_reply"


def test_invalid_draft_type_is_rejected(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-INVALID-TYPE")

    response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "unknown"})

    assert response.status_code == 422


def test_get_order_drafts_returns_created_drafts(client: TestClient) -> None:
    _, order = create_ready_order(client, uber_order_number="UBER-LIST-DRAFTS")
    initial_draft = create_initial_claim_draft(client, order["id"])
    followup_response = client.post(f"/v1/orders/{order['id']}/drafts", json={"draft_type": "followup_1"})
    assert followup_response.status_code == 201

    response = client.get(f"/v1/orders/{order['id']}/drafts")

    assert response.status_code == 200
    data = response.json()
    assert [draft["id"] for draft in data] == [initial_draft["id"], followup_response.json()["id"]]
    assert [draft["status"] for draft in data] == ["created", "created"]


def test_get_global_drafts_returns_created_drafts(client: TestClient) -> None:
    restaurant, order = create_ready_order(
        client,
        restaurant_name="Restaurant Global Drafts",
        uber_order_number="UBER-GLOBAL-DRAFTS",
    )
    draft = create_initial_claim_draft(client, order["id"])

    response = client.get("/v1/drafts")

    assert response.status_code == 200
    data = response.json()
    assert data == [
        {
            "id": draft["id"],
            "order_id": order["id"],
            "draft_type": "initial_claim",
            "subject": draft["subject"],
            "status": "created",
            "created_at": draft["created_at"],
            "restaurant_name": restaurant["name"],
            "uber_order_number": "UBER-GLOBAL-DRAFTS",
            "provider": None,
            "provider_status": None,
            "provider_draft_id": None,
            "provider_message_id": None,
            "provider_sent_at": None,
            "provider_to_email": None,
        }
    ]
