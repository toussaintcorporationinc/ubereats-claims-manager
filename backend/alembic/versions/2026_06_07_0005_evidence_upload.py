"""evidence upload metadata

Revision ID: 0005_evidence_upload
Revises: 0004_auth_roles
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_evidence_upload"
down_revision: Union[str, None] = "0004_auth_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evidence_files",
        sa.Column("storage_backend", sa.String(length=50), server_default="local", nullable=False),
    )
    op.add_column("evidence_files", sa.Column("checksum_sha256", sa.String(length=64), nullable=True))
    op.add_column("evidence_files", sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True))
    op.add_column(
        "evidence_files",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.add_column("evidence_files", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_evidence_files_uploaded_by_user_id", "evidence_files", ["uploaded_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_files_uploaded_by_user_id", table_name="evidence_files")
    op.drop_column("evidence_files", "deleted_at")
    op.drop_column("evidence_files", "created_at")
    op.drop_column("evidence_files", "uploaded_by_user_id")
    op.drop_column("evidence_files", "checksum_sha256")
    op.drop_column("evidence_files", "storage_backend")
