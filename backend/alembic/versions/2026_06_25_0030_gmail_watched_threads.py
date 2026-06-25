"""Add Gmail watched thread tracking.

Revision ID: 0030_gmail_watched_threads
Revises: 0029_gmail_labels
Create Date: 2026-06-25 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030_gmail_watched_threads"
down_revision = "0029_gmail_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gmail_watched_threads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("first_starred_message_id", sa.String(length=255), nullable=True),
        sa.Column("linked_case_type", sa.String(length=80), nullable=True),
        sa.Column("linked_case_id", sa.Integer(), nullable=True),
        sa.Column("claim_order_id", sa.Integer(), nullable=True),
        sa.Column("customer_refund_dispute_id", sa.Integer(), nullable=True),
        sa.Column("appeal_workflow_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("last_seen_history_id", sa.String(length=255), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("star_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'positive', 'payment_confirmed', 'manual_review', 'paused', 'closed')",
            name="ck_gmail_watched_threads_status",
        ),
        sa.ForeignKeyConstraint(["appeal_workflow_id"], ["appeal_workflows.id"]),
        sa.ForeignKeyConstraint(["claim_order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["customer_refund_dispute_id"], ["uber_customer_refund_disputes.id"]),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_account_id", "gmail_thread_id", name="uq_gmail_watched_threads_account_thread"),
    )
    op.create_index(
        "ix_gmail_watched_threads_email_account_id",
        "gmail_watched_threads",
        ["email_account_id"],
    )
    op.create_index("ix_gmail_watched_threads_last_message_at", "gmail_watched_threads", ["last_message_at"])
    op.create_index("ix_gmail_watched_threads_status", "gmail_watched_threads", ["status"])

    op.create_table(
        "gmail_starred_work_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watched_thread_id", sa.Integer(), nullable=True),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=True),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'positive', 'refused', "
            "'evidence_needed', 'manual_review', 'skipped', 'failed')",
            name="ck_gmail_starred_work_items_status",
        ),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_email_messages.id"]),
        sa.ForeignKeyConstraint(["watched_thread_id"], ["gmail_watched_threads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "email_account_id",
            "provider_message_id",
            name="uq_gmail_starred_work_items_account_message",
        ),
    )
    op.create_index(
        "ix_gmail_starred_work_items_email_account_id",
        "gmail_starred_work_items",
        ["email_account_id"],
    )
    op.create_index(
        "ix_gmail_starred_work_items_gmail_thread_id",
        "gmail_starred_work_items",
        ["gmail_thread_id"],
    )
    op.create_index("ix_gmail_starred_work_items_processed_at", "gmail_starred_work_items", ["processed_at"])
    op.create_index("ix_gmail_starred_work_items_status", "gmail_starred_work_items", ["status"])
    op.create_index(
        "ix_gmail_starred_work_items_watched_thread_id",
        "gmail_starred_work_items",
        ["watched_thread_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_gmail_starred_work_items_watched_thread_id", table_name="gmail_starred_work_items")
    op.drop_index("ix_gmail_starred_work_items_status", table_name="gmail_starred_work_items")
    op.drop_index("ix_gmail_starred_work_items_processed_at", table_name="gmail_starred_work_items")
    op.drop_index("ix_gmail_starred_work_items_gmail_thread_id", table_name="gmail_starred_work_items")
    op.drop_index("ix_gmail_starred_work_items_email_account_id", table_name="gmail_starred_work_items")
    op.drop_table("gmail_starred_work_items")
    op.drop_index("ix_gmail_watched_threads_status", table_name="gmail_watched_threads")
    op.drop_index("ix_gmail_watched_threads_last_message_at", table_name="gmail_watched_threads")
    op.drop_index("ix_gmail_watched_threads_email_account_id", table_name="gmail_watched_threads")
    op.drop_table("gmail_watched_threads")
