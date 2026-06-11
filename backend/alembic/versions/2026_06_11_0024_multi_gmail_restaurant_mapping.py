"""add restaurant gmail account mapping

Revision ID: 0024_multi_gmail_routing
Revises: 0023_resend_provider
Create Date: 2026-06-11 22:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_multi_gmail_routing"
down_revision: str | None = "0023_resend_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_account_restaurant_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("email_account_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["email_account_id"], ["email_accounts.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", name="uq_email_account_restaurant_mapping_restaurant"),
    )
    op.create_index(
        "ix_email_account_restaurant_mappings_email_account_id",
        "email_account_restaurant_mappings",
        ["email_account_id"],
    )
    op.create_index(
        "ix_email_account_restaurant_mappings_restaurant_id",
        "email_account_restaurant_mappings",
        ["restaurant_id"],
    )
    with op.batch_alter_table("email_provider_drafts") as batch_op:
        batch_op.add_column(sa.Column("email_account_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_email_provider_drafts_email_account_id",
            "email_accounts",
            ["email_account_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_email_provider_drafts_email_account_id",
            ["email_account_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("email_provider_drafts") as batch_op:
        batch_op.drop_index("ix_email_provider_drafts_email_account_id")
        batch_op.drop_constraint("fk_email_provider_drafts_email_account_id", type_="foreignkey")
        batch_op.drop_column("email_account_id")
    op.drop_index(
        "ix_email_account_restaurant_mappings_restaurant_id",
        table_name="email_account_restaurant_mappings",
    )
    op.drop_index(
        "ix_email_account_restaurant_mappings_email_account_id",
        table_name="email_account_restaurant_mappings",
    )
    op.drop_table("email_account_restaurant_mappings")
