"""add gmail response intelligence analysis

Revision ID: 0025_gmail_response_intel
Revises: 0024_multi_gmail_routing
Create Date: 2026-06-12 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_gmail_response_intel"
down_revision: str | None = "0024_multi_gmail_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_response_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("response_review_id", sa.Integer(), nullable=True),
        sa.Column("analyzed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("applied_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recommended_review_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("reason", sa.String(length=100), nullable=True),
        sa.Column("detected_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_payment_date", sa.Date(), nullable=True),
        sa.Column("evidence_requested", sa.Boolean(), nullable=True),
        sa.Column("matched_keywords_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('analyzed', 'applied', 'manual_review', 'ignored', 'failed')",
            name="ck_gmail_response_analyses_status",
        ),
        sa.CheckConstraint(
            "recommended_review_type IN ('accepted', 'payment_to_verify', 'payment_confirmed', 'refused', "
            "'evidence_requested', 'information_requested', 'followup_needed', 'ignored', 'manual_review')",
            name="ck_gmail_response_analyses_review_type",
        ),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_email_messages.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["response_review_id"], ["claim_response_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id", name="uq_gmail_response_analyses_inbound_message"),
    )
    op.create_index(
        "ix_gmail_response_analyses_inbound_message_id",
        "gmail_response_analyses",
        ["inbound_message_id"],
    )
    op.create_index("ix_gmail_response_analyses_order_id", "gmail_response_analyses", ["order_id"])
    op.create_index("ix_gmail_response_analyses_status", "gmail_response_analyses", ["status"])
    op.create_index(
        "ix_gmail_response_analyses_recommended_review_type",
        "gmail_response_analyses",
        ["recommended_review_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_response_analyses_recommended_review_type", table_name="gmail_response_analyses")
    op.drop_index("ix_gmail_response_analyses_status", table_name="gmail_response_analyses")
    op.drop_index("ix_gmail_response_analyses_order_id", table_name="gmail_response_analyses")
    op.drop_index("ix_gmail_response_analyses_inbound_message_id", table_name="gmail_response_analyses")
    op.drop_table("gmail_response_analyses")
