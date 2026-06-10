"""autopilot controlled send

Revision ID: 0020_autopilot
Revises: 0019_v1_1_rc2_fixes
Create Date: 2026-06-10 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_autopilot"
down_revision: str | None = "0019_v1_1_rc2_fixes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUTOPILOT_RUN_STATUSES = ("running", "completed", "failed", "stopped")
AUTOPILOT_MODES = ("initial_claims", "followups", "appeals", "all", "emergency_stop")
AUTOPILOT_CASE_TYPES = ("claim_order", "followup_task", "appeal_workflow")
AUTOPILOT_ACTION_TYPES = (
    "send_initial_claim",
    "send_followup_1",
    "send_followup_2",
    "send_escalation",
    "send_appeal",
    "request_more_evidence",
    "manual_review",
)
AUTOPILOT_ACTION_STATUSES = (
    "candidate",
    "skipped",
    "draft_created",
    "provider_draft_created",
    "sent",
    "failed",
    "manual_review",
)


def check_in_constraint(column_name: str, allowed_values: tuple[str, ...]) -> str:
    quoted_values = ", ".join(f"'{value}'" for value in allowed_values)
    return f"{column_name} IN ({quoted_values})"


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column("autopilot_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "autopilot_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=50), nullable=False),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(check_in_constraint("status", AUTOPILOT_RUN_STATUSES), name="ck_autopilot_runs_status"),
        sa.CheckConstraint(check_in_constraint("mode", AUTOPILOT_MODES), name="ck_autopilot_runs_mode"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autopilot_runs_status", "autopilot_runs", ["status"])
    op.create_index("ix_autopilot_runs_mode", "autopilot_runs", ["mode"])
    op.create_index("ix_autopilot_runs_created_at", "autopilot_runs", ["created_at"])

    op.create_table(
        "autopilot_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_type", sa.String(length=50), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("email_draft_id", sa.Integer(), nullable=True),
        sa.Column("provider_draft_id", sa.Integer(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(check_in_constraint("case_type", AUTOPILOT_CASE_TYPES), name="ck_autopilot_actions_case_type"),
        sa.CheckConstraint(
            check_in_constraint("action_type", AUTOPILOT_ACTION_TYPES),
            name="ck_autopilot_actions_action_type",
        ),
        sa.CheckConstraint(check_in_constraint("status", AUTOPILOT_ACTION_STATUSES), name="ck_autopilot_actions_status"),
        sa.ForeignKeyConstraint(["email_draft_id"], ["email_drafts.id"]),
        sa.ForeignKeyConstraint(["provider_draft_id"], ["email_provider_drafts.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["autopilot_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_autopilot_actions_run_id", "autopilot_actions", ["run_id"])
    op.create_index("ix_autopilot_actions_restaurant_id", "autopilot_actions", ["restaurant_id"])
    op.create_index("ix_autopilot_actions_case", "autopilot_actions", ["case_type", "case_id"])
    op.create_index("ix_autopilot_actions_status", "autopilot_actions", ["status"])
    op.create_index("ix_autopilot_actions_sent_at", "autopilot_actions", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_autopilot_actions_sent_at", table_name="autopilot_actions")
    op.drop_index("ix_autopilot_actions_status", table_name="autopilot_actions")
    op.drop_index("ix_autopilot_actions_case", table_name="autopilot_actions")
    op.drop_index("ix_autopilot_actions_restaurant_id", table_name="autopilot_actions")
    op.drop_index("ix_autopilot_actions_run_id", table_name="autopilot_actions")
    op.drop_table("autopilot_actions")

    op.drop_index("ix_autopilot_runs_created_at", table_name="autopilot_runs")
    op.drop_index("ix_autopilot_runs_mode", table_name="autopilot_runs")
    op.drop_index("ix_autopilot_runs_status", table_name="autopilot_runs")
    op.drop_table("autopilot_runs")

    op.drop_column("restaurants", "autopilot_enabled")
