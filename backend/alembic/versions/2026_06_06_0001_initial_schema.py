"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=False),
        sa.Column("uber_merchant_id", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "claim_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("internal_reference", sa.String(length=255), nullable=True),
        sa.Column("uber_order_number", sa.String(length=255), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("order_time", sa.Time(), nullable=True),
        sa.Column("cancellation_time", sa.Time(), nullable=True),
        sa.Column("order_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("accepted_by_restaurant", sa.Boolean(), nullable=True),
        sa.Column("prepared_before_cancellation", sa.Boolean(), nullable=True),
        sa.Column("loss_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_followup_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=100), nullable=True),
        sa.Column("recovered_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'missing_evidence', 'ready_to_send', 'draft_email_created', 'sent', "
            "'waiting_uber_response', 'followup_1_sent', 'followup_2_sent', 'escalation_sent', 'accepted', "
            "'payment_to_verify', 'payment_confirmed', 'refused', 'manual_review', 'closed')",
            name="ck_claim_orders_status",
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "uber_order_number", name="uq_claim_orders_restaurant_uber_order"),
    )
    op.create_index("ix_claim_orders_restaurant_id", "claim_orders", ["restaurant_id"], unique=False)
    op.create_index("ix_claim_orders_status", "claim_orders", ["status"], unique=False)
    op.create_table(
        "evidence_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', "
            "'uber_screenshot', 'other')",
            name="ck_evidence_files_type",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_files_order_id", "evidence_files", ["order_id"], unique=False)
    op.create_table(
        "email_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("draft_type", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "draft_type IN ('initial_claim', 'followup_1', 'followup_2', 'escalation', 'proof_reply')",
            name="ck_email_drafts_type",
        ),
        sa.CheckConstraint("status IN ('draft', 'ready', 'archived')", name="ck_email_drafts_status"),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_drafts_order_id", "email_drafts", ["order_id"], unique=False)
    op.create_table(
        "email_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), server_default="internal", nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("ai_classification", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("provider IN ('internal', 'gmail', 'microsoft_graph')", name="ck_email_threads_provider"),
        sa.CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_email_threads_direction"),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_threads_order_id", "email_threads", ["order_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_entity", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_email_threads_order_id", table_name="email_threads")
    op.drop_table("email_threads")
    op.drop_index("ix_email_drafts_order_id", table_name="email_drafts")
    op.drop_table("email_drafts")
    op.drop_index("ix_evidence_files_order_id", table_name="evidence_files")
    op.drop_table("evidence_files")
    op.drop_index("ix_claim_orders_status", table_name="claim_orders")
    op.drop_index("ix_claim_orders_restaurant_id", table_name="claim_orders")
    op.drop_table("claim_orders")
    op.drop_table("restaurants")
