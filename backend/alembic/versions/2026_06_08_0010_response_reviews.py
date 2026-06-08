"""manual response reviews

Revision ID: 0010_response_reviews
Revises: 0009_gmail_inbound_sync
Create Date: 2026-06-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_response_reviews"
down_revision: Union[str, None] = "0009_gmail_inbound_sync"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INBOUND_REVIEW_STATUS_CHECK = "review_status IN ('unreviewed', 'reviewed', 'ignored')"
REVIEW_TYPE_CHECK = (
    "review_type IN ('accepted', 'payment_to_verify', 'payment_confirmed', 'refused', "
    "'evidence_requested', 'information_requested', 'followup_needed', 'ignored', 'manual_review')"
)


def upgrade() -> None:
    add_inbound_review_columns()

    op.create_table(
        "claim_response_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=False),
        sa.Column("review_type", sa.String(length=50), nullable=False),
        sa.Column("previous_order_status", sa.String(length=50), nullable=False),
        sa.Column("new_order_status", sa.String(length=50), nullable=False),
        sa.Column("recovered_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_payment_date", sa.Date(), nullable=True),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("evidence_requested", sa.Boolean(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(REVIEW_TYPE_CHECK, name="ck_claim_response_reviews_type"),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_email_messages.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claim_response_reviews_inbound_message_id", "claim_response_reviews", ["inbound_message_id"])
    op.create_index("ix_claim_response_reviews_order_id", "claim_response_reviews", ["order_id"])
    op.create_index("ix_claim_response_reviews_review_type", "claim_response_reviews", ["review_type"])
    op.create_index(
        "ix_claim_response_reviews_reviewed_by_user_id",
        "claim_response_reviews",
        ["reviewed_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_claim_response_reviews_reviewed_by_user_id", table_name="claim_response_reviews")
    op.drop_index("ix_claim_response_reviews_review_type", table_name="claim_response_reviews")
    op.drop_index("ix_claim_response_reviews_order_id", table_name="claim_response_reviews")
    op.drop_index("ix_claim_response_reviews_inbound_message_id", table_name="claim_response_reviews")
    op.drop_table("claim_response_reviews")
    drop_inbound_review_columns()


def add_inbound_review_columns() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("inbound_email_messages", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("review_status", sa.String(length=50), nullable=False, server_default="unreviewed")
            )
            batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.add_column(sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
            batch_op.create_check_constraint("ck_inbound_email_review_status", INBOUND_REVIEW_STATUS_CHECK)
        return

    op.add_column(
        "inbound_email_messages",
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="unreviewed"),
    )
    op.add_column("inbound_email_messages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("inbound_email_messages", sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_inbound_email_review_status",
        "inbound_email_messages",
        INBOUND_REVIEW_STATUS_CHECK,
    )


def drop_inbound_review_columns() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("inbound_email_messages", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_inbound_email_review_status", type_="check")
            batch_op.drop_column("reviewed_by_user_id")
            batch_op.drop_column("reviewed_at")
            batch_op.drop_column("review_status")
        return

    op.drop_constraint("ck_inbound_email_review_status", "inbound_email_messages", type_="check")
    op.drop_column("inbound_email_messages", "reviewed_by_user_id")
    op.drop_column("inbound_email_messages", "reviewed_at")
    op.drop_column("inbound_email_messages", "review_status")
