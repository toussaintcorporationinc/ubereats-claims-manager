"""Store runtime owner-managed configuration such as Gmail OAuth credentials.

Revision ID: 0033_runtime_settings
Revises: 0032_verified_payment_accounting
Create Date: 2026-09-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0033_runtime_settings"
down_revision: str | Sequence[str] | None = "0032_verified_payment_accounting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value_plain", sa.Text(), nullable=True),
        sa.Column("value_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_runtime_settings_updated_at",
        "runtime_settings",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_settings_updated_at", table_name="runtime_settings")
    op.drop_table("runtime_settings")
