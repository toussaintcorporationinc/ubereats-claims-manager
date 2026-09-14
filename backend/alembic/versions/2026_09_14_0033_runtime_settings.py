"""Store runtime owner-managed configuration such as Gmail OAuth credentials.

Revision ID: 0033_runtime_settings
Revises: 0032_verified_payment_accounting
Create Date: 2026-09-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0033_runtime_settings"
down_revision: str | Sequence[str] | None = "0032_verified_payment_accounting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_settings (
            key VARCHAR(120) PRIMARY KEY,
            value_plain TEXT NULL,
            value_encrypted TEXT NULL,
            updated_by_user_id INTEGER NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_runtime_settings_updated_at
        ON runtime_settings(updated_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_runtime_settings_updated_at")
    op.execute("DROP TABLE IF EXISTS runtime_settings")
