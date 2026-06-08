"""gmail inbound sync

Revision ID: 0009_gmail_inbound_sync
Revises: 0008_gmail_send_tracking
Create Date: 2026-06-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_gmail_inbound_sync"
down_revision: Union[str, None] = "0008_gmail_send_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_CLAIM_STATUS_CHECK = (
    "status IN ('draft', 'missing_evidence', 'ready_to_send', 'draft_email_created', "
    "'sent', 'waiting_uber_response', 'response_received', 'followup_1_sent', "
    "'followup_2_sent', 'escalation_sent', 'accepted', 'payment_to_verify', "
    "'payment_confirmed', 'refused', 'manual_review', 'closed')"
)
OLD_CLAIM_STATUS_CHECK = (
    "status IN ('draft', 'missing_evidence', 'ready_to_send', 'draft_email_created', "
    "'sent', 'waiting_uber_response', 'followup_1_sent', 'followup_2_sent', "
    "'escalation_sent', 'accepted', 'payment_to_verify', 'payment_confirmed', "
    "'refused', 'manual_review', 'closed')"
)


def upgrade() -> None:
    replace_claim_order_status_check(NEW_CLAIM_STATUS_CHECK)

    op.create_table(
        "gmail_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("last_history_id", sa.String(length=255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('idle', 'running', 'success', 'failed')", name="ck_gmail_sync_states_status"),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gmail_sync_states_email_account_id",
        "gmail_sync_states",
        ["email_account_id"],
        unique=True,
    )

    op.create_table(
        "inbound_email_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=True),
        sa.Column("gmail_history_id", sa.String(length=255), nullable=True),
        sa.Column("from_email", sa.String(length=255), nullable=True),
        sa.Column("to_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_headers_json", sa.JSON(), nullable=True),
        sa.Column("match_status", sa.String(length=50), nullable=False),
        sa.Column("match_reason", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("provider IN ('gmail')", name="ck_inbound_email_provider"),
        sa.CheckConstraint(
            "match_status IN ('linked', 'unlinked', 'ignored')",
            name="ck_inbound_email_match_status",
        ),
        sa.CheckConstraint(
            "match_reason IN ('thread_id_match', 'order_number_match', 'subject_match', "
            "'manual_link', 'no_match', 'ignored_sender')",
            name="ck_inbound_email_match_reason",
        ),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_account_id",
            "provider_message_id",
            name="uq_inbound_email_messages_account_message",
        ),
    )
    op.create_index(
        "ix_inbound_email_messages_email_account_id",
        "inbound_email_messages",
        ["email_account_id"],
    )
    op.create_index("ix_inbound_email_messages_match_status", "inbound_email_messages", ["match_status"])
    op.create_index("ix_inbound_email_messages_order_id", "inbound_email_messages", ["order_id"])
    op.create_index(
        "ix_inbound_email_messages_provider_thread_id",
        "inbound_email_messages",
        ["provider_thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_email_messages_provider_thread_id", table_name="inbound_email_messages")
    op.drop_index("ix_inbound_email_messages_order_id", table_name="inbound_email_messages")
    op.drop_index("ix_inbound_email_messages_match_status", table_name="inbound_email_messages")
    op.drop_index("ix_inbound_email_messages_email_account_id", table_name="inbound_email_messages")
    op.drop_table("inbound_email_messages")
    op.drop_index("ix_gmail_sync_states_email_account_id", table_name="gmail_sync_states")
    op.drop_table("gmail_sync_states")

    op.execute("UPDATE claim_orders SET status = 'waiting_uber_response' WHERE status = 'response_received'")
    replace_claim_order_status_check(OLD_CLAIM_STATUS_CHECK)


def replace_claim_order_status_check(check_sql: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("claim_orders", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_claim_orders_status", type_="check")
            batch_op.create_check_constraint("ck_claim_orders_status", check_sql)
        return

    op.drop_constraint("ck_claim_orders_status", "claim_orders", type_="check")
    op.create_check_constraint("ck_claim_orders_status", "claim_orders", check_sql)
