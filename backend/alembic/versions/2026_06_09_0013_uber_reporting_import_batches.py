"""uber reporting import batches

Revision ID: 0013_uber_reporting_import_batches
Revises: 0012_uber_connector_foundation
Create Date: 2026-06-09 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_uber_reporting_import_batches"
down_revision: str | None = "0012_uber_connector_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uber_reporting_import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("valid_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("warning_rows", sa.Integer(), nullable=False),
        sa.Column("created_snapshots_count", sa.Integer(), nullable=False),
        sa.Column("created_transactions_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "report_type IN ('orders_report', 'payments_report', 'adjustments_report', 'combined_report')",
            name="ck_uber_reporting_import_batches_report_type",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsed', 'confirmed', 'partially_imported', 'failed', 'cancelled')",
            name="ck_uber_reporting_import_batches_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_uber_reporting_import_batches_uploaded_by_user_id",
        "uber_reporting_import_batches",
        ["uploaded_by_user_id"],
    )
    op.create_index("ix_uber_reporting_import_batches_status", "uber_reporting_import_batches", ["status"])
    op.create_index("ix_uber_reporting_import_batches_report_type", "uber_reporting_import_batches", ["report_type"])

    op.create_table(
        "uber_reporting_import_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("normalized_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_transaction_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('valid', 'invalid', 'warning', 'duplicate', 'created', 'skipped')",
            name="ck_uber_reporting_import_rows_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["uber_reporting_import_batches.id"]),
        sa.ForeignKeyConstraint(["created_snapshot_id"], ["uber_order_snapshots.id"]),
        sa.ForeignKeyConstraint(["created_transaction_id"], ["uber_financial_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uber_reporting_import_rows_batch_id", "uber_reporting_import_rows", ["batch_id"])
    op.create_index("ix_uber_reporting_import_rows_status", "uber_reporting_import_rows", ["status"])


def downgrade() -> None:
    op.drop_index("ix_uber_reporting_import_rows_status", table_name="uber_reporting_import_rows")
    op.drop_index("ix_uber_reporting_import_rows_batch_id", table_name="uber_reporting_import_rows")
    op.drop_table("uber_reporting_import_rows")
    op.drop_index("ix_uber_reporting_import_batches_report_type", table_name="uber_reporting_import_batches")
    op.drop_index("ix_uber_reporting_import_batches_status", table_name="uber_reporting_import_batches")
    op.drop_index(
        "ix_uber_reporting_import_batches_uploaded_by_user_id",
        table_name="uber_reporting_import_batches",
    )
    op.drop_table("uber_reporting_import_batches")
