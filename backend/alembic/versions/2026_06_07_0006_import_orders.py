"""order import batches

Revision ID: 0006_import_orders
Revises: 0005_evidence_upload
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_import_orders"
down_revision: Union[str, None] = "0005_evidence_upload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unauthorized_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_orders_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('uploaded', 'parsed', 'confirmed', 'partially_imported', 'failed', 'cancelled')",
            name="ck_import_batches_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_batches_status", "import_batches", ["status"])
    op.create_index("ix_import_batches_uploaded_by_user_id", "import_batches", ["uploaded_by_user_id"])

    op.create_table(
        "import_rows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("normalized_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_order_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint(
            "status IN ('valid', 'invalid', 'duplicate', 'unauthorized', 'created', 'skipped')",
            name="ck_import_rows_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_rows_batch_id", "import_rows", ["batch_id"])
    op.create_index("ix_import_rows_status", "import_rows", ["status"])


def downgrade() -> None:
    op.drop_index("ix_import_rows_status", table_name="import_rows")
    op.drop_index("ix_import_rows_batch_id", table_name="import_rows")
    op.drop_table("import_rows")
    op.drop_index("ix_import_batches_uploaded_by_user_id", table_name="import_batches")
    op.drop_index("ix_import_batches_status", table_name="import_batches")
    op.drop_table("import_batches")
