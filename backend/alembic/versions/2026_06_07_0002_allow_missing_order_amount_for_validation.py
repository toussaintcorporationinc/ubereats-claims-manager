"""allow missing order amount for validation

Revision ID: 0002_allow_missing_order_amount
Revises: 0001_initial_schema
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_allow_missing_order_amount"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("claim_orders") as batch_op:
        batch_op.alter_column(
            "order_amount",
            existing_type=sa.Numeric(12, 2),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("claim_orders") as batch_op:
        batch_op.alter_column(
            "order_amount",
            existing_type=sa.Numeric(12, 2),
            nullable=False,
        )

