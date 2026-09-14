from fastapi.testclient import TestClient

from app.main import app
from app.services.uber_connector_service import UberConnectorService


def test_uber_webhook_compatibility_alias_points_to_live_handler():
    assert UberConnectorService.process_webhook is UberConnectorService.handle_webhook_event


def test_first_registered_uber_webhook_processes_signed_payload(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        UberConnectorService,
        "verify_webhook_signature",
        lambda self, db, body, signature: signature == "valid-signature",
    )

    def fake_process(self, db, payload):
        captured.update(payload)
        return {"status": "processed"}

    monkeypatch.setattr(UberConnectorService, "process_webhook", fake_process)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uber/webhook",
            content=b'{"event_type":"store.provisioned","store_id":"store-test"}',
            headers={"X-Uber-Signature": "valid-signature", "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert captured == {"event_type": "store.provisioned", "store_id": "store-test"}


def test_uber_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(
        UberConnectorService,
        "verify_webhook_signature",
        lambda self, db, body, signature: False,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/uber/webhook",
            content=b'{"event_type":"orders.cancel"}',
            headers={"X-Uber-Signature": "invalid", "Content-Type": "application/json"},
        )

    assert response.status_code == 401
