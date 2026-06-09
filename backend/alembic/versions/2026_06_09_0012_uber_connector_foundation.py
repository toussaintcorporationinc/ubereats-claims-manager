"""uber connector foundation

Revision ID: 0012_uber_connector_foundation
Revises: 0011_followup_tasks
Create Date: 2026-06-09 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_uber_connector_foundation"
down_revision: str | None = "0011_followup_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uber_integration_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("client_id_encrypted", sa.Text(), nullable=True),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('uber_eats')", name="ck_uber_integration_accounts_provider"),
        sa.CheckConstraint(
            "status IN ('not_configured', 'pending_approval', 'connected', 'disconnected', 'disabled')",
            name="ck_uber_integration_accounts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uber_integration_accounts_provider", "uber_integration_accounts", ["provider"])
    op.create_index(
        "ix_uber_integration_accounts_created_by_user_id",
        "uber_integration_accounts",
        ["created_by_user_id"],
    )

    op.create_table(
        "uber_store_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("uber_store_id", sa.String(length=255), nullable=False),
        sa.Column("uber_store_name", sa.String(length=255), nullable=False),
        sa.Column("merchant_store_id", sa.String(length=255), nullable=True),
        sa.Column("external_reference_id", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uber_store_id", name="uq_uber_store_mappings_uber_store_id"),
    )
    op.create_index("ix_uber_store_mappings_restaurant_id", "uber_store_mappings", ["restaurant_id"])
    op.create_index("ix_uber_store_mappings_active", "uber_store_mappings", ["active"])

    op.create_table(
        "uber_order_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("uber_store_id", sa.String(length=255), nullable=False),
        sa.Column("uber_order_id", sa.String(length=255), nullable=False),
        sa.Column("display_id", sa.String(length=255), nullable=True),
        sa.Column("current_state", sa.String(length=100), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_total_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("imported_from", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "imported_from IN ('api_orders', 'api_reporting', 'manager_export')",
            name="ck_uber_order_snapshots_source",
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uber_store_id", "uber_order_id", name="uq_uber_order_snapshots_store_order"),
    )
    op.create_index("ix_uber_order_snapshots_restaurant_id", "uber_order_snapshots", ["restaurant_id"])
    op.create_index("ix_uber_order_snapshots_uber_order_id", "uber_order_snapshots", ["uber_order_id"])
    op.create_index("ix_uber_order_snapshots_current_state", "uber_order_snapshots", ["current_state"])

    op.create_table(
        "uber_financial_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("uber_store_id", sa.String(length=255), nullable=False),
        sa.Column("uber_order_id", sa.String(length=255), nullable=True),
        sa.Column("transaction_type", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("payout_reference", sa.String(length=255), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("imported_from", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "imported_from IN ('api_orders', 'api_reporting', 'manager_export')",
            name="ck_uber_financial_transactions_source",
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uber_financial_transactions_restaurant_id", "uber_financial_transactions", ["restaurant_id"])
    op.create_index("ix_uber_financial_transactions_uber_order_id", "uber_financial_transactions", ["uber_order_id"])
    op.create_index(
        "ix_uber_financial_transactions_transaction_date",
        "uber_financial_transactions",
        ["transaction_date"],
    )

    op.create_table(
        "uber_reconciliation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("uber_order_id", sa.String(length=255), nullable=False),
        sa.Column("claim_order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("order_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("missing_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("evidence_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('compensated', 'not_compensated', 'partially_compensated', 'needs_evidence', "
            "'already_claimed', 'ignored', 'manual_review')",
            name="ck_uber_reconciliation_results_status",
        ),
        sa.ForeignKeyConstraint(["claim_order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "uber_order_id", name="uq_uber_reconciliation_results_restaurant_order"),
    )
    op.create_index("ix_uber_reconciliation_results_restaurant_id", "uber_reconciliation_results", ["restaurant_id"])
    op.create_index("ix_uber_reconciliation_results_status", "uber_reconciliation_results", ["status"])
    op.create_index("ix_uber_reconciliation_results_claim_order_id", "uber_reconciliation_results", ["claim_order_id"])


def downgrade() -> None:
    op.drop_index("ix_uber_reconciliation_results_claim_order_id", table_name="uber_reconciliation_results")
    op.drop_index("ix_uber_reconciliation_results_status", table_name="uber_reconciliation_results")
    op.drop_index("ix_uber_reconciliation_results_restaurant_id", table_name="uber_reconciliation_results")
    op.drop_table("uber_reconciliation_results")
    op.drop_index("ix_uber_financial_transactions_transaction_date", table_name="uber_financial_transactions")
    op.drop_index("ix_uber_financial_transactions_uber_order_id", table_name="uber_financial_transactions")
    op.drop_index("ix_uber_financial_transactions_restaurant_id", table_name="uber_financial_transactions")
    op.drop_table("uber_financial_transactions")
    op.drop_index("ix_uber_order_snapshots_current_state", table_name="uber_order_snapshots")
    op.drop_index("ix_uber_order_snapshots_uber_order_id", table_name="uber_order_snapshots")
    op.drop_index("ix_uber_order_snapshots_restaurant_id", table_name="uber_order_snapshots")
    op.drop_table("uber_order_snapshots")
    op.drop_index("ix_uber_store_mappings_active", table_name="uber_store_mappings")
    op.drop_index("ix_uber_store_mappings_restaurant_id", table_name="uber_store_mappings")
    op.drop_table("uber_store_mappings")
    op.drop_index("ix_uber_integration_accounts_created_by_user_id", table_name="uber_integration_accounts")
    op.drop_index("ix_uber_integration_accounts_provider", table_name="uber_integration_accounts")
    op.drop_table("uber_integration_accounts")
