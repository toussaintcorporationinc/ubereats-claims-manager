"""Require official Uber reporting before counting recovered money.

Revision ID: 0032_verified_payment_accounting
Revises: 0031_asian_passion_identity
Create Date: 2026-07-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import json

from alembic import op
import sqlalchemy as sa


revision: str = "0032_verified_payment_accounting"
down_revision: str | Sequence[str] | None = "0031_asian_passion_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    claim_orders = sa.table(
        "claim_orders",
        sa.column("id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("result", sa.String),
        sa.column("recovered_amount", sa.Numeric),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    claim_reviews = sa.table(
        "claim_response_reviews",
        sa.column("id", sa.Integer),
        sa.column("order_id", sa.Integer),
        sa.column("inbound_message_id", sa.Integer),
        sa.column("review_type", sa.String),
        sa.column("new_order_status", sa.String),
        sa.column("recovered_amount", sa.Numeric),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    customer_refunds = sa.table(
        "uber_customer_refund_disputes",
        sa.column("id", sa.Integer),
        sa.column("claim_order_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("recovered_amount", sa.Numeric),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    customer_refund_reviews = sa.table(
        "customer_refund_dispute_reviews",
        sa.column("id", sa.Integer),
        sa.column("dispute_id", sa.Integer),
        sa.column("inbound_message_id", sa.Integer),
        sa.column("review_type", sa.String),
        sa.column("new_dispute_status", sa.String),
        sa.column("new_claim_order_status", sa.String),
        sa.column("recovered_amount", sa.Numeric),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    analyses = sa.table(
        "gmail_response_analyses",
        sa.column("id", sa.Integer),
        sa.column("response_review_id", sa.Integer),
        sa.column("recommended_review_type", sa.String),
        sa.column("reason", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    workflows = sa.table(
        "appeal_workflows",
        sa.column("id", sa.Integer),
        sa.column("claim_order_id", sa.Integer),
        sa.column("customer_refund_dispute_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    watched_threads = sa.table(
        "gmail_watched_threads",
        sa.column("id", sa.Integer),
        sa.column("claim_order_id", sa.Integer),
        sa.column("customer_refund_dispute_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    audit_logs = sa.table(
        "audit_logs",
        sa.column("user_id", sa.Integer),
        sa.column("entity_type", sa.String),
        sa.column("entity_id", sa.Integer),
        sa.column("action", sa.String),
        sa.column("old_value", sa.Text),
        sa.column("new_value", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    claim_review_rows = bind.execute(
        sa.select(claim_reviews.c.id, claim_reviews.c.order_id).where(
            claim_reviews.c.review_type == "payment_confirmed",
            claim_reviews.c.inbound_message_id.is_not(None),
        )
    ).all()
    customer_review_rows = bind.execute(
        sa.select(
            customer_refund_reviews.c.id,
            customer_refund_reviews.c.dispute_id,
            customer_refunds.c.claim_order_id,
        )
        .select_from(
            customer_refund_reviews.join(
                customer_refunds,
                customer_refunds.c.id == customer_refund_reviews.c.dispute_id,
            )
        )
        .where(
            customer_refund_reviews.c.review_type == "payment_confirmed",
            customer_refund_reviews.c.inbound_message_id.is_not(None),
        )
    ).all()

    claim_review_ids = [row.id for row in claim_review_rows]
    order_ids = {
        row.order_id for row in claim_review_rows if row.order_id is not None
    } | {
        row.claim_order_id for row in customer_review_rows if row.claim_order_id is not None
    }
    customer_review_ids = [row.id for row in customer_review_rows]
    dispute_ids = {row.dispute_id for row in customer_review_rows}

    if claim_review_ids:
        bind.execute(
            claim_reviews.update()
            .where(claim_reviews.c.id.in_(claim_review_ids))
            .values(
                review_type="payment_to_verify",
                new_order_status="payment_to_verify",
                recovered_amount=None,
                updated_at=now,
            )
        )
        bind.execute(
            analyses.update()
            .where(analyses.c.response_review_id.in_(claim_review_ids))
            .values(
                recommended_review_type="payment_to_verify",
                reason="payment_requires_uber_reconciliation",
                updated_at=now,
            )
        )

    if customer_review_ids:
        bind.execute(
            customer_refund_reviews.update()
            .where(customer_refund_reviews.c.id.in_(customer_review_ids))
            .values(
                review_type="payment_to_verify",
                new_dispute_status="payment_to_verify",
                new_claim_order_status="payment_to_verify",
                recovered_amount=None,
                updated_at=now,
            )
        )

    if order_ids:
        order_ids_without_official_credit = set(
            bind.execute(
                sa.select(claim_orders.c.id).where(
                    claim_orders.c.id.in_(order_ids),
                    claim_orders.c.status == "payment_confirmed",
                    claim_orders.c.result == "payment_confirmed",
                    ~sa.exists(
                        sa.select(sa.literal(1)).select_from(audit_logs).where(
                            audit_logs.c.entity_type == "claim_order",
                            audit_logs.c.entity_id == claim_orders.c.id,
                            audit_logs.c.action == "claim_order.payment_confirmed_from_uber_reporting",
                        )
                    ),
                )
            ).scalars()
        )
        if order_ids_without_official_credit:
            bind.execute(
                claim_orders.update()
                .where(claim_orders.c.id.in_(order_ids_without_official_credit))
                .values(
                    status="payment_to_verify",
                    result="payment_to_verify",
                    recovered_amount=None,
                    updated_at=now,
                )
            )
            bind.execute(
                workflows.update()
                .where(
                    workflows.c.claim_order_id.in_(order_ids_without_official_credit),
                    workflows.c.status == "payment_confirmed",
                )
                .values(status="payment_to_verify", updated_at=now)
            )
            bind.execute(
                watched_threads.update()
                .where(
                    watched_threads.c.claim_order_id.in_(order_ids_without_official_credit),
                    watched_threads.c.status == "payment_confirmed",
                )
                .values(status="positive", updated_at=now)
            )
            bind.execute(
                audit_logs.insert(),
                [
                    {
                        "user_id": None,
                        "entity_type": "claim_order",
                        "entity_id": order_id,
                        "action": "migration.gmail_payment_requires_uber_reconciliation",
                        "old_value": json.dumps({"status": "payment_confirmed"}),
                        "new_value": json.dumps(
                            {
                                "status": "payment_to_verify",
                                "recovered_amount": None,
                            }
                        ),
                        "created_at": now,
                    }
                    for order_id in sorted(order_ids_without_official_credit)
                ],
            )

    if dispute_ids:
        dispute_ids_without_official_credit = set(
            bind.execute(
                sa.select(customer_refunds.c.id).where(
                    customer_refunds.c.id.in_(dispute_ids),
                    customer_refunds.c.status == "payment_confirmed",
                    ~sa.exists(
                        sa.select(sa.literal(1)).select_from(audit_logs).where(
                            audit_logs.c.entity_type == "uber_customer_refund_dispute",
                            audit_logs.c.entity_id == customer_refunds.c.id,
                            audit_logs.c.action == "customer_refund.payment_confirmed_from_uber_reporting",
                        )
                    ),
                )
            ).scalars()
        )
        if dispute_ids_without_official_credit:
            bind.execute(
                customer_refunds.update()
                .where(customer_refunds.c.id.in_(dispute_ids_without_official_credit))
                .values(
                    status="payment_to_verify",
                    recovered_amount=None,
                    updated_at=now,
                )
            )
            bind.execute(
                workflows.update()
                .where(
                    workflows.c.customer_refund_dispute_id.in_(dispute_ids_without_official_credit),
                    workflows.c.status == "payment_confirmed",
                )
                .values(status="payment_to_verify", updated_at=now)
            )
            bind.execute(
                watched_threads.update()
                .where(
                    watched_threads.c.customer_refund_dispute_id.in_(dispute_ids_without_official_credit),
                    watched_threads.c.status == "payment_confirmed",
                )
                .values(status="positive", updated_at=now)
            )


def downgrade() -> None:
    # The migration intentionally avoids recreating unverified recovered amounts.
    pass
