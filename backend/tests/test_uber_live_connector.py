import hashlib
import hmac

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClaimOrder, Restaurant, UberOrderSnapshot, UberStoreMapping, User
from app.services.uber_connector_service import UberConnectorService


def test_uber_connector_credentials_and_signature(db_session: Session) -> None:
    owner = User(
        email="owner@example.com",
        hashed_password="unused",
        full_name="Owner",
        role="owner",
        active=True,
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)

    service = UberConnectorService()
    service.configure_credentials(
        db_session,
        owner,
        client_id="client-test-123",
        client_secret="secret-test-456",
    )

    status = service.get_status(db_session, owner)
    assert status["credentials_configured"] is True
    assert status["oauth_ready"] is True
    assert status["official_api_enabled"] is False
    assert status["status"] == "pending_approval"
    assert str(status["oauth_redirect_uri"]).endswith("/v1/uber/oauth/callback")
    assert str(status["webhook_url"]).endswith("/v1/uber/webhook")

    body = b'{"event_type":"orders.cancel","resource_id":"order-1"}'
    signature = hmac.new(b"secret-test-456", body, hashlib.sha256).hexdigest()
    assert service.verify_webhook_signature(db_session, body, signature) is True
    assert service.verify_webhook_signature(db_session, body, "deadbeef") is False


def test_uber_oauth_url_is_passive_setup_ready(db_session: Session) -> None:
    owner = User(
        email="owner2@example.com",
        hashed_password="unused",
        full_name="Owner",
        role="owner",
        active=True,
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(owner)

    service = UberConnectorService()
    service.configure_credentials(
        db_session,
        owner,
        client_id="client-test-abc",
        client_secret="secret-test-def",
    )
    url = service.build_authorization_url(db_session, owner)

    assert "auth.uber.com/oauth/v2/authorize" in url
    assert "eats.pos_provisioning" in url
    assert "client-test-abc" in url
    assert "state=" in url



def test_uber_cancellation_webhook_captures_snapshot_and_provisional_claim(
    db_session: Session,
    monkeypatch,
) -> None:
    owner = User(
        email="owner3@example.com",
        hashed_password="unused",
        full_name="Owner",
        role="owner",
        active=True,
    )
    restaurant = Restaurant(
        name="Moon Pizza",
        sender_email="moon@example.com",
        uber_merchant_id="store-live-1",
        active=True,
        autopilot_enabled=True,
    )
    db_session.add_all([owner, restaurant])
    db_session.flush()
    mapping = UberStoreMapping(
        restaurant_id=restaurant.id,
        uber_store_id="store-live-1",
        uber_store_name="Moon Pizza",
        active=True,
    )
    db_session.add(mapping)
    db_session.commit()

    service = UberConnectorService()
    service.configure_credentials(
        db_session,
        owner,
        client_id="client-live",
        client_secret="secret-live",
    )

    monkeypatch.setattr(
        service,
        "get_order",
        lambda db, order_id: {
            "id": order_id,
            "display_id": "AB123",
            "current_state": "CANCELED",
            "store": {"id": "store-live-1", "name": "Moon Pizza"},
            "eater": {"first_name": "Client", "last_name": "T"},
            "placed_at": "2026-09-14T18:00:00+02:00",
            "payment": {
                "charges": {
                    "total": {
                        "amount": 2890,
                        "currency_code": "EUR",
                    }
                }
            },
        },
    )

    result = service.handle_webhook_event(
        db_session,
        {
            "event_type": "orders.cancel",
            "event_id": "event-live-1",
            "event_time": 1789402800,
            "meta": {
                "resource_id": "order-live-1",
                "user_id": "store-live-1",
                "status": "pos",
            },
        },
    )

    assert result["status"] == "captured"
    snapshot = db_session.scalar(
        select(UberOrderSnapshot).where(UberOrderSnapshot.uber_order_id == "order-live-1")
    )
    assert snapshot is not None
    assert snapshot.current_state == "CANCELED"
    assert snapshot.order_total_amount == Decimal("28.90")
    assert snapshot.imported_from == "api_orders"

    claim = db_session.scalar(
        select(ClaimOrder).where(
            ClaimOrder.restaurant_id == restaurant.id,
            ClaimOrder.uber_order_number == "AB123",
        )
    )
    assert claim is not None
    assert claim.loss_type == "uber_live_cancellation"
    assert claim.status == "missing_evidence"
    assert claim.prepared_before_cancellation is None


def test_uber_poll_worker_is_safe_with_no_mapped_stores(
    db_session: Session,
    monkeypatch,
) -> None:
    owner = User(
        email="owner4@example.com",
        hashed_password="unused",
        full_name="Owner",
        role="owner",
        active=True,
    )
    db_session.add(owner)
    db_session.commit()

    service = UberConnectorService()
    service.configure_credentials(
        db_session,
        owner,
        client_id="client-poll",
        client_secret="secret-poll",
    )
    monkeypatch.setattr(service, "client_credentials_token", lambda db: "app-token")

    result = service.poll_cancellations(db_session)

    assert result.stores_checked == 0
    assert result.cancellations_seen == 0
    assert result.snapshots_created == 0
    assert result.snapshots_updated == 0
    assert result.errors == ()
