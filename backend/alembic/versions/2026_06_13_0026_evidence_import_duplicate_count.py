"""Track removed duplicate evidence import files.

Revision ID: 0026_evidence_duplicate_count
Revises: 0025_gmail_response_intel
Create Date: 2026-06-13 02:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_evidence_duplicate_count"
down_revision: str | Sequence[str] | None = "0025_gmail_response_intel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_import_batches",
        sa.Column("duplicate_files_count", sa.Integer(), nullable=False, server_default="0"),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("evidence_import_batches", "duplicate_files_count", server_default=None)


def downgrade() -> None:
    op.drop_column("evidence_import_batches", "duplicate_files_count")
