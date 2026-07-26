from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ClaimOrder, UberCustomerRefundDispute


def test_recovery_machine_splits_refunds_and_cancellations(
    client: TestClient,
    db_session: Session,
) -> None:
    restaurant_response = client.post(
        "/v1/restaurants",
        json={"name": "Krousty Bat", "sender_email": "claims@example.com"},
    )
    assert restaurant_response.status_code == 201
    restaurant_id = restaurant_response.json()["id"]

    db_session.add(
        UberCustomerRefundDispute(
            restaurant_id=restaurant_id,
            uber_order_id="UBER-REFUND-1",
            display_id="REF-1",
            dispute_type="order_not_received",
            reason="customer_reported_not_received",
            status="needs_evidence",
            customer_refund_amount=Decimal("29.99"),
            currency="EUR",
            evidence_required=True,
            evidence_status="missing",
        )
    )
    db_session.add(
        ClaimOrder(
            restaurant_id=restaurant_id,
            uber_order_number="UBER-CANCEL-1",
            order_amount=Decimal("34.00"),
            currency="EUR",
            status="missing_evidence",
            loss_type="cancellation_not_compensated",
        )
    )
    db_session.add(
        ClaimOrder(
            restaurant_id=restaurant_id,
            uber_order_number="UBER-CANCEL-PAID",
            order_amount=Decimal("18.50"),
            recovered_amount=Decimal("18.50"),
            currency="EUR",
            status="payment_confirmed",
            loss_type="cancellation_not_compensated",
        )
    )
    db_session.commit()

    response = client.get("/v1/workspace/recovery-machine")

    assert response.status_code == 200
    payload = response.json()
    rails = {rail["key"]: rail for rail in payload["rails"]}
    assert set(rails) == {"refunds", "cancellations"}
    assert rails["refunds"]["title"] == "Remboursements"
    assert rails["refunds"]["detected_count"] == 1
    assert rails["refunds"]["missing_evidence_count"] == 1
    assert rails["cancellations"]["title"] == "Annulations"
    assert rails["cancellations"]["detected_count"] == 2
    assert rails["cancellations"]["missing_evidence_count"] == 1
    assert rails["cancellations"]["recovered_amount"] == "18.50"
    refund_evidence = stage_by_key(rails["refunds"], "evidence_needed")
    cancellation_evidence = stage_by_key(rails["cancellations"], "evidence_needed")
    assert "remboursement" in refund_evidence["description"]
    assert "annulation" in cancellation_evidence["description"]


def test_recovery_machine_empty_state_is_stable(client: TestClient) -> None:
    response = client.get("/v1/workspace/recovery-machine")

    assert response.status_code == 200
    payload = response.json()
    assert payload["global_progress_percent"] == 0
    assert len(payload["rails"]) == 2
    assert all(rail["health"] == "empty" for rail in payload["rails"])


def stage_by_key(rail: dict, key: str) -> dict:
    return next(stage for stage in rail["stages"] if stage["key"] == key)
