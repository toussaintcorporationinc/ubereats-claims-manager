import hashlib
import hmac

from sqlalchemy.orm import Session

from app.models import User
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
