"""customer refund reviews and recovery cockpit fields

Revision ID: 0017_refund_reviews
Revises: 0016_customer_refunds
Create Date: 2026-06-09 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_refund_reviews"
down_revision: str | None = "0016_customer_refunds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_TYPE_CHECK = (
    "review_type IN ('accepted', 'payment_to_verify', 'payment_confirmed', 'refused', "
    "'evidence_requested', 'information_requested', 'followup_needed', 'ignored', 'manual_review')"
)


def upgrade() -> None:
    op.add_column("uber_customer_refund_disputes", sa.Column("recovered_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("uber_customer_refund_disputes", sa.Column("expected_payment_date", sa.Date(), nullable=True))
    op.add_column("uber_customer_refund_disputes", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uber_customer_refund_disputes", sa.Column("last_reviewed_by_user_id", sa.Integer(), nullable=True))

    op.create_table(
        "customer_refund_dispute_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dispute_id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(length=50), nullable=False),
        sa.Column("previous_dispute_status", sa.String(length=50), nullable=False),
        sa.Column("new_dispute_status", sa.String(length=50), nullable=False),
        sa.Column("previous_claim_order_status", sa.String(length=50), nullable=True),
        sa.Column("new_claim_order_status", sa.String(length=50), nullable=True),
        sa.Column("recovered_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_payment_date", sa.Date(), nullable=True),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("evidence_requested", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(REVIEW_TYPE_CHECK, name="ck_customer_refund_dispute_reviews_type"),
        sa.ForeignKeyConstraint(["dispute_id"], ["uber_customer_refund_disputes.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_email_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customer_refund_dispute_reviews_dispute_id", "customer_refund_dispute_reviews", ["dispute_id"])
    op.create_index(
        "ix_customer_refund_dispute_reviews_inbound_message_id",
        "customer_refund_dispute_reviews",
        ["inbound_message_id"],
    )
    op.create_index(
        "ix_customer_refund_dispute_reviews_reviewed_by_user_id",
        "customer_refund_dispute_reviews",
        ["reviewed_by_user_id"],
    )
    op.create_index("ix_customer_refund_dispute_reviews_review_type", "customer_refund_dispute_reviews", ["review_type"])


def downgrade() -> None:
    op.drop_index("ix_customer_refund_dispute_reviews_review_type", table_name="customer_refund_dispute_reviews")
    op.drop_index("ix_customer_refund_dispute_reviews_reviewed_by_user_id", table_name="customer_refund_dispute_reviews")
    op.drop_index("ix_customer_refund_dispute_reviews_inbound_message_id", table_name="customer_refund_dispute_reviews")
    op.drop_index("ix_customer_refund_dispute_reviews_dispute_id", table_name="customer_refund_dispute_reviews")
    op.drop_table("customer_refund_dispute_reviews")

    op.drop_column("uber_customer_refund_disputes", "last_reviewed_by_user_id")
    op.drop_column("uber_customer_refund_disputes", "last_reviewed_at")
    op.drop_column("uber_customer_refund_disputes", "expected_payment_date")
    op.drop_column("uber_customer_refund_disputes", "recovered_amount")
