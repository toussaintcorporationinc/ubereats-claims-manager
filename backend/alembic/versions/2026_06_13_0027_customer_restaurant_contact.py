"""Add restaurant phone and Uber snapshot customer names.

Revision ID: 0027_customer_restaurant_contact
Revises: 0026_evidence_duplicate_count
Create Date: 2026-06-13 19:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_customer_restaurant_contact"
down_revision: str | Sequence[str] | None = "0026_evidence_duplicate_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("phone_number", sa.String(length=50), nullable=True))
    op.add_column("uber_order_snapshots", sa.Column("customer_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("uber_order_snapshots", "customer_name")
    op.drop_column("restaurants", "phone_number")
