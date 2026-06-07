"""gmail email provider drafts

Revision ID: 0007_gmail_email_provider
Revises: 0006_import_orders
Create Date: 2026-06-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_gmail_email_provider"
down_revision: Union[str, None] = "0006_import_orders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("provider IN ('gmail')", name="ck_email_accounts_provider"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_accounts_provider_email", "email_accounts", ["provider", "email_address"])
    op.create_index("ix_email_accounts_user_provider", "email_accounts", ["user_id", "provider"])

    op.create_table(
        "email_provider_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_draft_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_draft_id", sa.String(length=255), nullable=True),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=True),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("provider IN ('gmail')", name="ck_email_provider_drafts_provider"),
        sa.CheckConstraint(
            "status IN ('provider_draft_created', 'failed')",
            name="ck_email_provider_drafts_status",
        ),
        sa.ForeignKeyConstraint(["email_draft_id"], ["email_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_provider_drafts_created_by_user_id",
        "email_provider_drafts",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_email_provider_drafts_email_draft_id",
        "email_provider_drafts",
        ["email_draft_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_provider_drafts_email_draft_id", table_name="email_provider_drafts")
    op.drop_index("ix_email_provider_drafts_created_by_user_id", table_name="email_provider_drafts")
    op.drop_table("email_provider_drafts")
    op.drop_index("ix_email_accounts_user_provider", table_name="email_accounts")
    op.drop_index("ix_email_accounts_provider_email", table_name="email_accounts")
    op.drop_table("email_accounts")
