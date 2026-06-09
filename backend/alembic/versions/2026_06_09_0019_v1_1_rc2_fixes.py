"""v1.1 rc2 staging fixes

Revision ID: 0019_v1_1_rc2_fixes
Revises: 0018_evidence_appeals
Create Date: 2026-06-09 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_v1_1_rc2_fixes"
down_revision: str | None = "0018_evidence_appeals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("uber_reconciliation_results", sa.Column("financial_status", sa.String(length=50), nullable=True))
    op.create_index(
        "ix_uber_reconciliation_results_financial_status",
        "uber_reconciliation_results",
        ["financial_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_uber_reconciliation_results_financial_status", table_name="uber_reconciliation_results")
    op.drop_column("uber_reconciliation_results", "financial_status")
