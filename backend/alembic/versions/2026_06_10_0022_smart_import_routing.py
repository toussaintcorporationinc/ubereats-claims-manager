"""smart import routing persistence

Revision ID: 0022_smart_import_routing
Revises: 0021_smart_import_workspace
Create Date: 2026-06-10 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_smart_import_routing"
down_revision: str | None = "0021_smart_import_workspace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_BATCH_STATUS_CHECK = "status IN ('previewed', 'confirmed', 'cancelled')"
NEW_BATCH_STATUS_CHECK = "status IN ('previewed', 'confirmed', 'cancelled', 'expired')"
FILE_STATUS_CHECK = "status IN ('previewed', 'confirmed', 'routed', 'ignored', 'failed', 'expired', 'manual_review')"


def _batch_recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    with op.batch_alter_table("smart_import_preview_batches", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_smart_import_preview_batches_status", type_="check")
        batch_op.add_column(sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint("ck_smart_import_preview_batches_status", NEW_BATCH_STATUS_CHECK)

    with op.batch_alter_table("smart_import_preview_files", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.add_column(sa.Column("temp_storage_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mime_type", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("checksum_sha256", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(length=50), nullable=False, server_default="previewed"))
        batch_op.add_column(sa.Column("destination_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("destination_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("destination_url", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.create_check_constraint("ck_smart_import_preview_files_status", FILE_STATUS_CHECK)

    op.create_index("ix_smart_import_preview_files_status", "smart_import_preview_files", ["status"])
    op.create_index("ix_smart_import_preview_files_checksum_sha256", "smart_import_preview_files", ["checksum_sha256"])


def downgrade() -> None:
    op.drop_index("ix_smart_import_preview_files_checksum_sha256", table_name="smart_import_preview_files")
    op.drop_index("ix_smart_import_preview_files_status", table_name="smart_import_preview_files")

    with op.batch_alter_table("smart_import_preview_files", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_smart_import_preview_files_status", type_="check")
        batch_op.drop_column("error_message")
        batch_op.drop_column("destination_url")
        batch_op.drop_column("destination_id")
        batch_op.drop_column("destination_type")
        batch_op.drop_column("status")
        batch_op.drop_column("checksum_sha256")
        batch_op.drop_column("file_size")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("temp_storage_path")

    with op.batch_alter_table("smart_import_preview_batches", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_smart_import_preview_batches_status", type_="check")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("total_files")
        batch_op.create_check_constraint("ck_smart_import_preview_batches_status", OLD_BATCH_STATUS_CHECK)
