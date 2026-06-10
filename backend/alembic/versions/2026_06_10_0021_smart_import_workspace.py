"""smart import previews and workspace actions

Revision ID: 0021_smart_import_workspace
Revises: 0020_autopilot
Create Date: 2026-06-10 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_smart_import_workspace"
down_revision: str | None = "0020_autopilot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SMART_IMPORT_PREVIEW_STATUSES = ("previewed", "confirmed", "cancelled")
SMART_IMPORT_FILE_CATEGORIES = ("uber_reporting", "evidence", "zip", "unknown")
SMART_IMPORT_RECOMMENDED_ACTIONS = (
    "import_uber_reporting",
    "import_evidence_bulk",
    "manual_review",
    "ignore",
)


def check_in_constraint(column_name: str, allowed_values: tuple[str, ...]) -> str:
    quoted_values = ", ".join(f"'{value}'" for value in allowed_values)
    return f"{column_name} IN ({quoted_values})"


def upgrade() -> None:
    op.create_table(
        "smart_import_preview_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="previewed"),
        sa.Column("files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            check_in_constraint("status", SMART_IMPORT_PREVIEW_STATUSES),
            name="ck_smart_import_preview_batches_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_smart_import_preview_batches_uploaded_by_user_id",
        "smart_import_preview_batches",
        ["uploaded_by_user_id"],
    )
    op.create_index("ix_smart_import_preview_batches_status", "smart_import_preview_batches", ["status"])

    op.create_table(
        "smart_import_preview_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("detected_category", sa.String(length=50), nullable=False),
        sa.Column("detected_report_type", sa.String(length=50), nullable=True),
        sa.Column("detected_evidence_type", sa.String(length=50), nullable=True),
        sa.Column("detected_restaurant_name", sa.String(length=255), nullable=True),
        sa.Column("detected_date_from", sa.Date(), nullable=True),
        sa.Column("detected_date_to", sa.Date(), nullable=True),
        sa.Column("header_row_number", sa.Integer(), nullable=True),
        sa.Column("skipped_preamble_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("recommended_action", sa.String(length=50), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("detected_columns", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            check_in_constraint("detected_category", SMART_IMPORT_FILE_CATEGORIES),
            name="ck_smart_import_preview_files_category",
        ),
        sa.CheckConstraint(
            check_in_constraint("recommended_action", SMART_IMPORT_RECOMMENDED_ACTIONS),
            name="ck_smart_import_preview_files_recommended_action",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["smart_import_preview_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_smart_import_preview_files_batch_id", "smart_import_preview_files", ["batch_id"])
    op.create_index(
        "ix_smart_import_preview_files_detected_category",
        "smart_import_preview_files",
        ["detected_category"],
    )
    op.create_index(
        "ix_smart_import_preview_files_recommended_action",
        "smart_import_preview_files",
        ["recommended_action"],
    )


def downgrade() -> None:
    op.drop_index("ix_smart_import_preview_files_recommended_action", table_name="smart_import_preview_files")
    op.drop_index("ix_smart_import_preview_files_detected_category", table_name="smart_import_preview_files")
    op.drop_index("ix_smart_import_preview_files_batch_id", table_name="smart_import_preview_files")
    op.drop_table("smart_import_preview_files")
    op.drop_index("ix_smart_import_preview_batches_status", table_name="smart_import_preview_batches")
    op.drop_index(
        "ix_smart_import_preview_batches_uploaded_by_user_id",
        table_name="smart_import_preview_batches",
    )
    op.drop_table("smart_import_preview_batches")
