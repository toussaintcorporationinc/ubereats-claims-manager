"""evidence request tasks

Revision ID: 0015_evidence_tasks
Revises: 0014_uber_reco_runs
Create Date: 2026-06-09 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_evidence_tasks"
down_revision: str | None = "0014_uber_reco_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_request_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("reconciliation_result_id", sa.Integer(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("required_evidence_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("skipped_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("last_upload_evidence_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "task_type IN ('missing_receipt', 'missing_cancellation_proof', 'missing_preparation_proof', 'missing_waste_photo', 'missing_uber_screenshot', 'evidence_review')",
            name="ck_evidence_request_tasks_task_type",
        ),
        sa.CheckConstraint(
            "required_evidence_type IN ('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', 'uber_screenshot', 'other')",
            name="ck_evidence_request_tasks_required_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'uploaded', 'completed', 'skipped', 'cancelled')",
            name="ck_evidence_request_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_evidence_request_tasks_priority",
        ),
        sa.ForeignKeyConstraint(["last_upload_evidence_id"], ["evidence_files.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["reconciliation_result_id"], ["uber_reconciliation_results.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_request_tasks_assigned_to_user_id", "evidence_request_tasks", ["assigned_to_user_id"])
    op.create_index("ix_evidence_request_tasks_due_at", "evidence_request_tasks", ["due_at"])
    op.create_index("ix_evidence_request_tasks_order_id", "evidence_request_tasks", ["order_id"])
    op.create_index("ix_evidence_request_tasks_priority", "evidence_request_tasks", ["priority"])
    op.create_index("ix_evidence_request_tasks_reconciliation_result_id", "evidence_request_tasks", ["reconciliation_result_id"])
    op.create_index("ix_evidence_request_tasks_restaurant_id", "evidence_request_tasks", ["restaurant_id"])
    op.create_index("ix_evidence_request_tasks_required_type", "evidence_request_tasks", ["required_evidence_type"])
    op.create_index("ix_evidence_request_tasks_status", "evidence_request_tasks", ["status"])
    op.create_index("ix_evidence_request_tasks_task_type", "evidence_request_tasks", ["task_type"])

    op.create_table(
        "evidence_upload_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["evidence_request_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_upload_links_expires_at", "evidence_upload_links", ["expires_at"])
    op.create_index("ix_evidence_upload_links_task_id", "evidence_upload_links", ["task_id"])
    op.create_index("ix_evidence_upload_links_token_hash", "evidence_upload_links", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_evidence_upload_links_token_hash", table_name="evidence_upload_links")
    op.drop_index("ix_evidence_upload_links_task_id", table_name="evidence_upload_links")
    op.drop_index("ix_evidence_upload_links_expires_at", table_name="evidence_upload_links")
    op.drop_table("evidence_upload_links")
    op.drop_index("ix_evidence_request_tasks_task_type", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_status", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_required_type", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_restaurant_id", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_reconciliation_result_id", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_priority", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_order_id", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_due_at", table_name="evidence_request_tasks")
    op.drop_index("ix_evidence_request_tasks_assigned_to_user_id", table_name="evidence_request_tasks")
    op.drop_table("evidence_request_tasks")
