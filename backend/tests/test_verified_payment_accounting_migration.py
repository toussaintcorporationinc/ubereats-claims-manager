from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    AppealWorkflow,
    AuditLog,
    ClaimOrder,
    ClaimResponseReview,
    CustomerRefundDisputeReview,
    EmailAccount,
    GmailResponseAnalysis,
    GmailWatchedThread,
    InboundEmailMessage,
    Restaurant,
    UberCustomerRefundDispute,
    User,
)
from app.models.domain import utc_now


def test_verified_payment_migration_clears_only_unverified_gmail_recoveries() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    work_dir = repo_root / "work"
    work_dir.mkdir(exist_ok=True)
    db_path = work_dir / "test_verified_payment_accounting_migration.db"
    if db_path.exists():
        db_path.unlink()

    backend_dir = repo_root / "backend"
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.attributes["database_url"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine = None

    try:
        command.upgrade(config, "0031_asian_passion_identity")
        engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
        with Session(engine) as db:
            user = User(
                email="verified-payment-migration@example.com",
                hashed_password="not-used",
                full_name="Migration Owner",
                role="owner",
                active=True,
            )
            restaurant = Restaurant(
                name="Asian Passion",
                sender_email="claims@example.com",
                autopilot_enabled=True,
            )
            db.add_all([user, restaurant])
            db.flush()
            account = EmailAccount(
                user_id=user.id,
                provider="gmail",
                email_address="claims@example.com",
                connected_at=utc_now(),
            )
            db.add(account)
            db.flush()

            unverified_order = ClaimOrder(
                restaurant_id=restaurant.id,
                uber_order_number="UNVERIFIED-1",
                customer_name="Unverified Customer",
                order_date=date(2026, 7, 15),
                order_amount=Decimal("46.80"),
                currency="EUR",
                status="payment_confirmed",
                result="payment_confirmed",
                recovered_amount=Decimal("46.80"),
            )
            official_order = ClaimOrder(
                restaurant_id=restaurant.id,
                uber_order_number="OFFICIAL-1",
                customer_name="Official Customer",
                order_date=date(2026, 7, 16),
                order_amount=Decimal("24.90"),
                currency="EUR",
                status="payment_confirmed",
                result="payment_confirmed_from_uber_reporting",
                recovered_amount=Decimal("24.90"),
            )
            db.add_all([unverified_order, official_order])
            db.flush()

            unverified_message = InboundEmailMessage(
                email_account_id=account.id,
                order_id=unverified_order.id,
                provider="gmail",
                provider_message_id="unverified-payment-email",
                provider_thread_id="unverified-payment-thread",
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Re: UNVERIFIED-1",
                body_text="Un paiement de 46,80 EUR a ete accorde.",
                received_at=utc_now(),
                raw_headers_json={},
                provider_labels_json=["INBOX"],
                match_status="linked",
                match_reason="order_number_match",
                review_status="reviewed",
                reviewed_at=utc_now(),
                reviewed_by_user_id=user.id,
            )
            official_message = InboundEmailMessage(
                email_account_id=account.id,
                order_id=official_order.id,
                provider="gmail",
                provider_message_id="official-payment-email",
                provider_thread_id="official-payment-thread",
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Re: OFFICIAL-1",
                body_text="Un paiement de 24,90 EUR a ete accorde.",
                received_at=utc_now(),
                raw_headers_json={},
                provider_labels_json=["INBOX"],
                match_status="linked",
                match_reason="order_number_match",
                review_status="reviewed",
                reviewed_at=utc_now(),
                reviewed_by_user_id=user.id,
            )
            db.add_all([unverified_message, official_message])
            db.flush()

            unverified_review = ClaimResponseReview(
                order_id=unverified_order.id,
                inbound_message_id=unverified_message.id,
                reviewed_by_user_id=user.id,
                review_type="payment_confirmed",
                previous_order_status="refused",
                new_order_status="payment_confirmed",
                recovered_amount=Decimal("46.80"),
            )
            official_review = ClaimResponseReview(
                order_id=official_order.id,
                inbound_message_id=official_message.id,
                reviewed_by_user_id=user.id,
                review_type="payment_confirmed",
                previous_order_status="payment_to_verify",
                new_order_status="payment_confirmed",
                recovered_amount=Decimal("24.90"),
            )
            db.add_all([unverified_review, official_review])
            db.flush()
            db.add_all(
                [
                    GmailResponseAnalysis(
                        inbound_message_id=unverified_message.id,
                        order_id=unverified_order.id,
                        response_review_id=unverified_review.id,
                        recommended_review_type="payment_confirmed",
                        status="applied",
                        confidence_score=Decimal("0.98"),
                        reason="payment_confirmed_with_amount",
                        detected_amount=Decimal("46.80"),
                    ),
                    GmailResponseAnalysis(
                        inbound_message_id=official_message.id,
                        order_id=official_order.id,
                        response_review_id=official_review.id,
                        recommended_review_type="payment_confirmed",
                        status="applied",
                        confidence_score=Decimal("0.98"),
                        reason="payment_confirmed_with_amount",
                        detected_amount=Decimal("24.90"),
                    ),
                ]
            )

            dispute = UberCustomerRefundDispute(
                restaurant_id=restaurant.id,
                uber_order_id=unverified_order.uber_order_number,
                display_id=unverified_order.uber_order_number,
                claim_order_id=unverified_order.id,
                customer_refund_reference="UNVERIFIED-REFUND-1",
                dispute_type="customer_refund",
                reason="customer_reported_missing_item",
                status="payment_confirmed",
                customer_refund_amount=Decimal("46.80"),
                order_amount=Decimal("46.80"),
                currency="EUR",
                evidence_status="complete",
                recovered_amount=Decimal("46.80"),
            )
            db.add(dispute)
            db.flush()
            customer_review = CustomerRefundDisputeReview(
                dispute_id=dispute.id,
                inbound_message_id=unverified_message.id,
                reviewed_by_user_id=user.id,
                review_type="payment_confirmed",
                previous_dispute_status="refused",
                new_dispute_status="payment_confirmed",
                previous_claim_order_status="refused",
                new_claim_order_status="payment_confirmed",
                recovered_amount=Decimal("46.80"),
            )
            workflow = AppealWorkflow(
                case_type="claim_order",
                case_id=unverified_order.id,
                restaurant_id=restaurant.id,
                claim_order_id=unverified_order.id,
                customer_refund_dispute_id=dispute.id,
                status="payment_confirmed",
            )
            watched = GmailWatchedThread(
                email_account_id=account.id,
                gmail_thread_id=unverified_message.provider_thread_id,
                first_starred_message_id=unverified_message.provider_message_id,
                claim_order_id=unverified_order.id,
                customer_refund_dispute_id=dispute.id,
                linked_case_type="claim_order",
                linked_case_id=unverified_order.id,
                status="payment_confirmed",
                star_active=False,
            )
            db.add_all([customer_review, workflow, watched])
            db.add(
                AuditLog(
                    user_id=user.id,
                    entity_type="claim_order",
                    entity_id=official_order.id,
                    action="claim_order.payment_confirmed_from_uber_reporting",
                    new_value='{"recovered_amount": "24.90"}',
                )
            )
            db.commit()
            ids = {
                "unverified_order": unverified_order.id,
                "official_order": official_order.id,
                "unverified_review": unverified_review.id,
                "official_review": official_review.id,
                "dispute": dispute.id,
                "customer_review": customer_review.id,
                "workflow": workflow.id,
                "watched": watched.id,
            }

        engine.dispose()
        engine = None
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
        with Session(engine) as db:
            unverified_order = db.get(ClaimOrder, ids["unverified_order"])
            official_order = db.get(ClaimOrder, ids["official_order"])
            unverified_review = db.get(ClaimResponseReview, ids["unverified_review"])
            official_review = db.get(ClaimResponseReview, ids["official_review"])
            dispute = db.get(UberCustomerRefundDispute, ids["dispute"])
            customer_review = db.get(CustomerRefundDisputeReview, ids["customer_review"])
            workflow = db.get(AppealWorkflow, ids["workflow"])
            watched = db.get(GmailWatchedThread, ids["watched"])

            assert unverified_order is not None
            assert unverified_order.status == "payment_to_verify"
            assert unverified_order.result == "payment_to_verify"
            assert unverified_order.recovered_amount is None
            assert unverified_review is not None
            assert unverified_review.review_type == "payment_to_verify"
            assert unverified_review.recovered_amount is None

            assert official_order is not None
            assert official_order.status == "payment_confirmed"
            assert official_order.result == "payment_confirmed_from_uber_reporting"
            assert official_order.recovered_amount == Decimal("24.90")
            assert official_review is not None
            assert official_review.review_type == "payment_to_verify"
            assert official_review.recovered_amount is None

            assert dispute is not None
            assert dispute.status == "payment_to_verify"
            assert dispute.recovered_amount is None
            assert customer_review is not None
            assert customer_review.review_type == "payment_to_verify"
            assert customer_review.recovered_amount is None
            assert workflow is not None and workflow.status == "payment_to_verify"
            assert watched is not None and watched.status == "positive"
    finally:
        if engine is not None:
            engine.dispose()
        if db_path.exists():
            db_path.unlink()
