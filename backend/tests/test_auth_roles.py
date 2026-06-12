import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_owner(client: TestClient, email: str = "owner@example.com") -> dict:
    response = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "owner-password", "full_name": "Owner Test"},
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()


def create_restaurant(client: TestClient, token: str, name: str = "Restaurant Auth") -> dict:
    response = client.post(
        "/v1/restaurants",
        json={"name": name, "sender_email": "claims@example.com"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def create_user(client: TestClient, token: str, email: str, role: str) -> dict:
    response = client.post(
        "/v1/users",
        json={
            "email": email,
            "password": "user-password",
            "full_name": f"{role.title()} Test",
            "role": role,
            "active": True,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def assign_restaurant(client: TestClient, token: str, user_id: int, restaurant_id: int) -> dict:
    response = client.post(
        f"/v1/users/{user_id}/restaurants",
        json={"restaurant_id": restaurant_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def order_payload(restaurant_id: int, uber_order_number: str = "UBER-AUTH-1") -> dict:
    return {
        "restaurant_id": restaurant_id,
        "uber_order_number": uber_order_number,
        "order_amount": "19.90",
        "currency": "EUR",
        "accepted_by_restaurant": True,
        "prepared_before_cancellation": True,
    }


def create_order(client: TestClient, token: str, restaurant_id: int, uber_order_number: str = "UBER-AUTH-1") -> dict:
    response = client.post(
        "/v1/orders",
        json=order_payload(restaurant_id, uber_order_number),
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def add_evidence(client: TestClient, token: str, order_id: int, evidence_type: str) -> dict:
    response = client.post(
        f"/v1/orders/{order_id}/evidence",
        json={
            "evidence_type": evidence_type,
            "original_filename": f"{evidence_type}.png",
            "storage_path": f"storage/evidence/{evidence_type}.png",
            "mime_type": "image/png",
            "file_size": 1024,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()


def test_health_public_works(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bootstrap_first_owner_via_register_ok(unauthenticated_client: TestClient) -> None:
    data = register_owner(unauthenticated_client)

    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["user"]["role"] == "owner"
    assert data["user"]["email"] == "owner@example.com"


def test_second_public_register_is_refused(unauthenticated_client: TestClient) -> None:
    register_owner(unauthenticated_client)

    response = unauthenticated_client.post(
        "/v1/auth/register",
        json={"email": "second@example.com", "password": "owner-password"},
    )

    assert response.status_code == 403


def test_owner_login_ok(unauthenticated_client: TestClient) -> None:
    register_owner(unauthenticated_client)

    data = login(unauthenticated_client, "owner@example.com", "owner-password")

    assert data["access_token"]
    assert data["user"]["role"] == "owner"


def test_login_wrong_password_is_refused(unauthenticated_client: TestClient) -> None:
    register_owner(unauthenticated_client)

    response = unauthenticated_client.post(
        "/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_auth_me_with_token_ok(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)

    response = unauthenticated_client.get("/v1/auth/me", headers=auth_headers(owner["access_token"]))

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"


def test_protected_endpoint_without_token_is_refused(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/v1/restaurants")

    assert response.status_code == 401


def test_owner_can_create_restaurant(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)

    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])

    assert restaurant["name"] == "Restaurant Auth"


def test_staff_cannot_create_restaurant(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    create_user(unauthenticated_client, owner["access_token"], "staff@example.com", "staff")
    staff_login = login(unauthenticated_client, "staff@example.com", "user-password")

    response = unauthenticated_client.post(
        "/v1/restaurants",
        json={"name": "Forbidden", "sender_email": "claims@example.com"},
        headers=auth_headers(staff_login["access_token"]),
    )

    assert response.status_code == 403


def test_owner_can_update_restaurant(unauthenticated_client: TestClient, db_session: Session) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])

    response = unauthenticated_client.patch(
        f"/v1/restaurants/{restaurant['id']}",
        json={
            "name": "Krousty Bat",
            "sender_email": "  Tiramisumaisonfrance@GMAIL.com  ",
            "uber_merchant_id": "merchant-krousty",
            "autopilot_enabled": True,
        },
        headers=auth_headers(owner["access_token"]),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Krousty Bat"
    assert data["sender_email"] == "tiramisumaisonfrance@gmail.com"
    assert data["uber_merchant_id"] == "merchant-krousty"
    assert data["autopilot_enabled"] is True

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "restaurant",
            AuditLog.entity_id == restaurant["id"],
            AuditLog.action == "restaurant.updated",
        )
    )
    assert audit_log is not None
    assert json.loads(audit_log.new_value or "{}")["sender_email"] == "tiramisumaisonfrance@gmail.com"


def test_manager_cannot_update_restaurant_settings(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")
    assign_restaurant(unauthenticated_client, owner["access_token"], manager["id"], restaurant["id"])
    manager_login = login(unauthenticated_client, "manager@example.com", "user-password")

    response = unauthenticated_client.patch(
        f"/v1/restaurants/{restaurant['id']}",
        json={"sender_email": "manager-change@example.com"},
        headers=auth_headers(manager_login["access_token"]),
    )

    assert response.status_code == 403


def test_owner_can_create_user_manager(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)

    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")

    assert manager["email"] == "manager@example.com"
    assert manager["role"] == "manager"


def test_owner_can_assign_restaurant_to_manager(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")

    access = assign_restaurant(unauthenticated_client, owner["access_token"], manager["id"], restaurant["id"])

    assert access["user_id"] == manager["id"]
    assert access["restaurant_id"] == restaurant["id"]


def test_manager_sees_only_assigned_restaurants(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    visible_restaurant = create_restaurant(unauthenticated_client, owner["access_token"], "Visible")
    create_restaurant(unauthenticated_client, owner["access_token"], "Hidden")
    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")
    assign_restaurant(unauthenticated_client, owner["access_token"], manager["id"], visible_restaurant["id"])
    manager_login = login(unauthenticated_client, "manager@example.com", "user-password")

    response = unauthenticated_client.get(
        "/v1/restaurants",
        headers=auth_headers(manager_login["access_token"]),
    )

    assert response.status_code == 200
    assert [restaurant["name"] for restaurant in response.json()] == ["Visible"]


def test_staff_can_create_order_on_assigned_restaurant(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    staff = create_user(unauthenticated_client, owner["access_token"], "staff@example.com", "staff")
    assign_restaurant(unauthenticated_client, owner["access_token"], staff["id"], restaurant["id"])
    staff_login = login(unauthenticated_client, "staff@example.com", "user-password")

    order = create_order(unauthenticated_client, staff_login["access_token"], restaurant["id"])

    assert order["restaurant_id"] == restaurant["id"]


def test_staff_cannot_create_order_on_unassigned_restaurant(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    create_restaurant(unauthenticated_client, owner["access_token"], "Assigned")
    create_user(unauthenticated_client, owner["access_token"], "staff@example.com", "staff")
    staff_login = login(unauthenticated_client, "staff@example.com", "user-password")

    response = unauthenticated_client.post(
        "/v1/orders",
        json=order_payload(restaurant["id"]),
        headers=auth_headers(staff_login["access_token"]),
    )

    assert response.status_code == 403


def test_manager_can_validate_order_for_assigned_restaurant(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")
    assign_restaurant(unauthenticated_client, owner["access_token"], manager["id"], restaurant["id"])
    manager_login = login(unauthenticated_client, "manager@example.com", "user-password")
    manager_token = manager_login["access_token"]
    order = create_order(unauthenticated_client, manager_token, restaurant["id"])
    add_evidence(unauthenticated_client, manager_token, order["id"], "cancellation_proof")
    add_evidence(unauthenticated_client, manager_token, order["id"], "preparation_proof")

    response = unauthenticated_client.post(
        f"/v1/orders/{order['id']}/validate",
        headers=auth_headers(manager_token),
    )

    assert response.status_code == 200
    assert response.json()["new_status"] == "ready_to_send"


def test_staff_cannot_generate_draft(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    staff = create_user(unauthenticated_client, owner["access_token"], "staff@example.com", "staff")
    assign_restaurant(unauthenticated_client, owner["access_token"], staff["id"], restaurant["id"])
    staff_login = login(unauthenticated_client, "staff@example.com", "user-password")
    order = create_order(unauthenticated_client, owner["access_token"], restaurant["id"])
    add_evidence(unauthenticated_client, owner["access_token"], order["id"], "cancellation_proof")
    add_evidence(unauthenticated_client, owner["access_token"], order["id"], "preparation_proof")
    validate_response = unauthenticated_client.post(
        f"/v1/orders/{order['id']}/validate",
        headers=auth_headers(owner["access_token"]),
    )
    assert validate_response.status_code == 200

    response = unauthenticated_client.post(
        f"/v1/orders/{order['id']}/drafts",
        json={"draft_type": "initial_claim"},
        headers=auth_headers(staff_login["access_token"]),
    )

    assert response.status_code == 403


def test_owner_can_view_global_dashboard(unauthenticated_client: TestClient) -> None:
    owner = register_owner(unauthenticated_client)
    first_restaurant = create_restaurant(unauthenticated_client, owner["access_token"], "A")
    second_restaurant = create_restaurant(unauthenticated_client, owner["access_token"], "B")
    create_order(unauthenticated_client, owner["access_token"], first_restaurant["id"], "UBER-DASH-1")
    create_order(unauthenticated_client, owner["access_token"], second_restaurant["id"], "UBER-DASH-2")

    response = unauthenticated_client.get("/v1/dashboard/summary", headers=auth_headers(owner["access_token"]))

    assert response.status_code == 200
    assert response.json()["total_orders"] == 2
    assert len(response.json()["orders_by_restaurant"]) == 2


def test_audit_log_created_for_user_creation(unauthenticated_client: TestClient, db_session: Session) -> None:
    owner = register_owner(unauthenticated_client)
    user = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "user",
            AuditLog.entity_id == user["id"],
            AuditLog.action == "user.created",
        )
    )

    assert audit_log is not None


def test_audit_log_created_for_restaurant_assignment(unauthenticated_client: TestClient, db_session: Session) -> None:
    owner = register_owner(unauthenticated_client)
    restaurant = create_restaurant(unauthenticated_client, owner["access_token"])
    manager = create_user(unauthenticated_client, owner["access_token"], "manager@example.com", "manager")
    access = assign_restaurant(unauthenticated_client, owner["access_token"], manager["id"], restaurant["id"])

    audit_log = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "user_restaurant_access",
            AuditLog.entity_id == access["id"],
            AuditLog.action == "user_restaurant_access.created",
        )
    )

    assert audit_log is not None
