"""Add import row link indexes.

Revision ID: 0028_import_row_link_indexes
Revises: 0027_customer_restaurant_contact
Create Date: 2026-06-16 03:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_import_row_link_indexes"
down_revision: str | Sequence[str] | None = "0027_customer_restaurant_contact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_uber_reporting_import_rows_created_snapshot_id",
        "uber_reporting_import_rows",
        ["created_snapshot_id"],
    )
    op.create_index(
        "ix_uber_reporting_import_rows_created_transaction_id",
        "uber_reporting_import_rows",
        ["created_transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_uber_reporting_import_rows_created_transaction_id",
        table_name="uber_reporting_import_rows",
    )
    op.drop_index(
        "ix_uber_reporting_import_rows_created_snapshot_id",
        table_name="uber_reporting_import_rows",
    )
