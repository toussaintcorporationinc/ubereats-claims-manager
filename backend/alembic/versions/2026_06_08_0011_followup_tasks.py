"""controlled followup tasks

Revision ID: 0011_followup_tasks
Revises: 0010_response_reviews
Create Date: 2026-06-08 04:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_followup_tasks"
down_revision: str | None = "0010_response_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FOLLOWUP_TASK_TYPE_CHECK = (
    "task_type IN ('followup_1', 'followup_2', 'escalation', 'manual_review', 'payment_verification')"
)
FOLLOWUP_TASK_STATUS_CHECK = (
    "status IN ('pending', 'draft_created', 'provider_draft_created', 'completed', 'skipped', 'cancelled')"
)


def upgrade() -> None:
    op.create_table(
        "followup_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_email_draft_id", sa.Integer(), nullable=True),
        sa.Column("generated_provider_draft_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("skipped_by_user_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(FOLLOWUP_TASK_TYPE_CHECK, name="ck_followup_tasks_type"),
        sa.CheckConstraint(FOLLOWUP_TASK_STATUS_CHECK, name="ck_followup_tasks_status"),
        sa.ForeignKeyConstraint(["generated_email_draft_id"], ["email_drafts.id"]),
        sa.ForeignKeyConstraint(["generated_provider_draft_id"], ["email_provider_drafts.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["claim_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "task_type", name="uq_followup_tasks_order_task_type"),
    )
    op.create_index("ix_followup_tasks_due_at", "followup_tasks", ["due_at"])
    op.create_index("ix_followup_tasks_order_id", "followup_tasks", ["order_id"])
    op.create_index("ix_followup_tasks_status", "followup_tasks", ["status"])
    op.create_index("ix_followup_tasks_task_type", "followup_tasks", ["task_type"])


def downgrade() -> None:
    op.drop_index("ix_followup_tasks_task_type", table_name="followup_tasks")
    op.drop_index("ix_followup_tasks_status", table_name="followup_tasks")
    op.drop_index("ix_followup_tasks_order_id", table_name="followup_tasks")
    op.drop_index("ix_followup_tasks_due_at", table_name="followup_tasks")
    op.drop_table("followup_tasks")
