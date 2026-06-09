"""uber reconciliation runs

Revision ID: 0014_uber_reco_runs
Revises: 0013_uber_reporting_import
Create Date: 2026-06-09 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_uber_reco_runs"
down_revision: str | None = "0013_uber_reporting_import"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uber_reconciliation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_orders_analyzed", sa.Integer(), nullable=False),
        sa.Column("canceled_orders_count", sa.Integer(), nullable=False),
        sa.Column("compensated_count", sa.Integer(), nullable=False),
        sa.Column("not_compensated_count", sa.Integer(), nullable=False),
        sa.Column("partially_compensated_count", sa.Integer(), nullable=False),
        sa.Column("already_claimed_count", sa.Integer(), nullable=False),
        sa.Column("needs_evidence_count", sa.Integer(), nullable=False),
        sa.Column("manual_review_count", sa.Integer(), nullable=False),
        sa.Column("total_claimable_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_missing_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_uber_reconciliation_runs_status",
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uber_reconciliation_runs_created_by_user_id", "uber_reconciliation_runs", ["created_by_user_id"])
    op.create_index("ix_uber_reconciliation_runs_restaurant_id", "uber_reconciliation_runs", ["restaurant_id"])
    op.create_index("ix_uber_reconciliation_runs_status", "uber_reconciliation_runs", ["status"])

    with op.batch_alter_table("uber_reconciliation_results") as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("display_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"))
        batch_op.add_column(sa.Column("confidence_score", sa.Numeric(5, 2), nullable=True))
        batch_op.add_column(sa.Column("matched_transaction_ids_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("matched_snapshot_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_uber_reconciliation_results_run_id",
            "uber_reconciliation_runs",
            ["run_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_uber_reconciliation_results_snapshot_id",
            "uber_order_snapshots",
            ["matched_snapshot_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("uber_reconciliation_results") as batch_op:
        batch_op.drop_constraint("fk_uber_reconciliation_results_snapshot_id", type_="foreignkey")
        batch_op.drop_constraint("fk_uber_reconciliation_results_run_id", type_="foreignkey")
        batch_op.drop_column("matched_snapshot_id")
        batch_op.drop_column("matched_transaction_ids_json")
        batch_op.drop_column("confidence_score")
        batch_op.drop_column("currency")
        batch_op.drop_column("display_id")
        batch_op.drop_column("run_id")
    op.drop_index("ix_uber_reconciliation_runs_status", table_name="uber_reconciliation_runs")
    op.drop_index("ix_uber_reconciliation_runs_restaurant_id", table_name="uber_reconciliation_runs")
    op.drop_index("ix_uber_reconciliation_runs_created_by_user_id", table_name="uber_reconciliation_runs")
    op.drop_table("uber_reconciliation_runs")
