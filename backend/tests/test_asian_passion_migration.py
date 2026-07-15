from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    AppealAttempt,
    AppealWorkflow,
    ClaimOrder,
    EmailAccount,
    EmailDraft,
    EmailProviderDraft,
    GmailStarredWorkItem,
    GmailWatchedThread,
    InboundEmailMessage,
    Restaurant,
    User,
)
from app.models.domain import utc_now


def test_asian_passion_migration_requeues_latest_starred_thread() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    work_dir = repo_root / "work"
    work_dir.mkdir(exist_ok=True)
    db_path = work_dir / "test_asian_passion_migration.db"
    if db_path.exists():
        db_path.unlink()

    config = Config("alembic.ini")
    config.attributes["database_url"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    engine = None

    try:
        command.upgrade(config, "0030_gmail_watched_threads")
        engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
        with Session(engine) as db:
            user = User(
                email="migration-owner@example.com",
                hashed_password="not-used",
                full_name="Migration Owner",
                role="owner",
                active=True,
            )
            restaurant = Restaurant(
                name="Crousty Best",
                sender_email="claims@example.com",
                autopilot_enabled=True,
            )
            db.add_all([user, restaurant])
            db.flush()
            order = ClaimOrder(
                restaurant_id=restaurant.id,
                uber_order_number="ASIAN-MIGRATION-1",
                customer_name="Client Migration",
                order_date=date(2026, 7, 1),
                order_amount=Decimal("38.50"),
                currency="EUR",
                status="refused",
            )
            account = EmailAccount(
                user_id=user.id,
                provider="gmail",
                email_address="claims@example.com",
                connected_at=utc_now(),
            )
            db.add_all([order, account])
            db.flush()
            inbound = InboundEmailMessage(
                email_account_id=account.id,
                order_id=order.id,
                provider="gmail",
                provider_message_id="migration-refusal",
                provider_thread_id="migration-thread",
                from_email="restaurantsfrance@uber.com",
                to_email=account.email_address,
                subject="Re: Crousty Best ASIAN-MIGRATION-1",
                body_text="Nous maintenons le refus.",
                received_at=utc_now(),
                raw_headers_json={},
                provider_labels_json=["INBOX", "STARRED"],
                match_status="linked",
                match_reason="order_number_match",
                review_status="reviewed",
                reviewed_at=utc_now(),
                reviewed_by_user_id=user.id,
            )
            db.add(inbound)
            db.flush()
            workflow = AppealWorkflow(
                case_type="claim_order",
                case_id=order.id,
                restaurant_id=restaurant.id,
                claim_order_id=order.id,
                status="appeal_needed",
                next_action_type="send_manual_appeal",
            )
            db.add(workflow)
            db.flush()
            watched = GmailWatchedThread(
                email_account_id=account.id,
                gmail_thread_id=inbound.provider_thread_id,
                first_starred_message_id=inbound.provider_message_id,
                claim_order_id=order.id,
                appeal_workflow_id=workflow.id,
                linked_case_type="claim_order",
                linked_case_id=order.id,
                status="manual_review",
                star_active=True,
            )
            old_draft = EmailDraft(
                order_id=order.id,
                draft_type="appeal_generic_refusal",
                subject="Re: Crousty Best ASIAN-MIGRATION-1",
                body="Bonjour, relance Crousty Best.\n\nCrousty Best",
                status="created",
            )
            db.add_all([watched, old_draft])
            db.flush()
            provider_draft = EmailProviderDraft(
                email_draft_id=old_draft.id,
                email_account_id=account.id,
                provider="gmail",
                provider_draft_id="migration-old-draft",
                provider_thread_id=inbound.provider_thread_id,
                to_email="restaurantsfrance@uber.com",
                subject=old_draft.subject,
                status="provider_draft_created",
                created_by_user_id=user.id,
            )
            db.add(provider_draft)
            db.flush()
            db.add(
                AppealAttempt(
                    workflow_id=workflow.id,
                    attempt_number=1,
                    appeal_type="first_appeal",
                    status="gmail_draft_created",
                    based_on_refusal_message_id=inbound.id,
                    email_draft_id=old_draft.id,
                    provider_draft_id=provider_draft.id,
                    created_by_user_id=user.id,
                )
            )
            work_item = GmailStarredWorkItem(
                watched_thread_id=watched.id,
                email_account_id=account.id,
                inbound_message_id=inbound.id,
                gmail_thread_id=watched.gmail_thread_id,
                provider_message_id=inbound.provider_message_id,
                status="processed",
                reason="gmail_reply_sent",
                processed_at=utc_now(),
            )
            db.add(work_item)
            db.commit()
            ids = {
                "restaurant": restaurant.id,
                "inbound": inbound.id,
                "watched": watched.id,
                "provider_draft": provider_draft.id,
                "work_item": work_item.id,
            }

        engine.dispose()
        engine = None
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
        with Session(engine) as db:
            restaurant = db.get(Restaurant, ids["restaurant"])
            inbound = db.get(InboundEmailMessage, ids["inbound"])
            watched = db.get(GmailWatchedThread, ids["watched"])
            provider_draft = db.get(EmailProviderDraft, ids["provider_draft"])
            work_item = db.get(GmailStarredWorkItem, ids["work_item"])

            assert restaurant is not None and restaurant.name == "Asian Passion"
            assert inbound is not None and inbound.review_status == "unreviewed"
            assert watched is not None and watched.status == "active"
            assert provider_draft is not None and provider_draft.status == "failed"
            assert provider_draft.last_error == "superseded_restaurant_identity"
            assert work_item is not None and work_item.status == "pending"
            assert work_item.reason == "restaurant_identity_rename_reanalysis"
            assert work_item.processed_at is None
    finally:
        if engine is not None:
            engine.dispose()
        if db_path.exists():
            db_path.unlink()
