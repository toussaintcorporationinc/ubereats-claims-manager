"""customer refund disputes

Revision ID: 0016_customer_refunds
Revises: 0015_evidence_tasks
Create Date: 2026-06-09 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_customer_refunds"
down_revision: str | None = "0015_evidence_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EVIDENCE_CHECK = (
    "evidence_type IN ('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', 'uber_screenshot', 'other')"
)
NEW_EVIDENCE_CHECK = (
    "evidence_type IN ('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', 'uber_screenshot', "
    "'delivery_proof', 'packaging_photo', 'sealed_bag_photo', 'courier_statement', 'gps_or_route_proof', "
    "'customer_contact_proof', 'order_details_screenshot', 'other')"
)
OLD_REQUIRED_EVIDENCE_CHECK = OLD_EVIDENCE_CHECK.replace("evidence_type", "required_evidence_type")
NEW_REQUIRED_EVIDENCE_CHECK = NEW_EVIDENCE_CHECK.replace("evidence_type", "required_evidence_type")
OLD_EMAIL_DRAFT_TYPE_CHECK = (
    "draft_type IN ('initial_claim', 'followup_1', 'followup_2', 'escalation', 'proof_reply')"
)
NEW_EMAIL_DRAFT_TYPE_CHECK = (
    "draft_type IN ('initial_claim', 'followup_1', 'followup_2', 'escalation', 'proof_reply', "
    "'customer_refund_order_not_received', 'customer_refund_missing_item', "
    "'customer_refund_order_error_adjustment', 'customer_refund_generic')"
)


def _batch_recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    with op.batch_alter_table("evidence_files", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_evidence_files_type", type_="check")
        batch_op.create_check_constraint("ck_evidence_files_type", NEW_EVIDENCE_CHECK)

    with op.batch_alter_table("email_drafts", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_email_drafts_type", type_="check")
        batch_op.create_check_constraint("ck_email_drafts_type", NEW_EMAIL_DRAFT_TYPE_CHECK)

    op.create_table(
        "uber_customer_refund_disputes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("uber_store_id", sa.String(length=255), nullable=True),
        sa.Column("uber_order_id", sa.String(length=255), nullable=True),
        sa.Column("display_id", sa.String(length=255), nullable=True),
        sa.Column("claim_order_id", sa.Integer(), nullable=True),
        sa.Column("financial_transaction_id", sa.Integer(), nullable=True),
        sa.Column("customer_refund_reference", sa.String(length=255), nullable=True),
        sa.Column("dispute_type", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("customer_refund_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("order_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("deducted_at", sa.Date(), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("evidence_required", sa.Boolean(), nullable=False),
        sa.Column("evidence_status", sa.String(length=50), nullable=False),
        sa.Column("dispute_email_draft_id", sa.Integer(), nullable=True),
        sa.Column("provider_draft_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ignored_by_user_id", sa.Integer(), nullable=True),
        sa.Column("ignore_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "dispute_type IN ('order_not_received', 'missing_item', 'incorrect_item', 'damaged_order', 'quality_issue', "
            "'customer_refund', 'order_error_adjustment', 'chargeback', 'unknown')",
            name="ck_customer_refund_disputes_type",
        ),
        sa.CheckConstraint(
            "reason IN ('customer_reported_not_received', 'customer_reported_missing_item', 'customer_reported_wrong_item', "
            "'customer_reported_quality_issue', 'uber_adjustment_order_error', 'refund_without_sufficient_proof', "
            "'self_delivery_dispute', 'unknown_reason')",
            name="ck_customer_refund_disputes_reason",
        ),
        sa.CheckConstraint(
            "status IN ('detected', 'needs_evidence', 'evidence_ready', 'draft_created', 'gmail_draft_created', 'sent', "
            "'accepted', 'payment_to_verify', 'payment_confirmed', 'refused', 'ignored', 'manual_review')",
            name="ck_customer_refund_disputes_status",
        ),
        sa.CheckConstraint(
            "evidence_status IN ('missing', 'partial', 'complete', 'not_required', 'manual_review')",
            name="ck_customer_refund_disputes_evidence_status",
        ),
        sa.ForeignKeyConstraint(["claim_order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["dispute_email_draft_id"], ["email_drafts.id"]),
        sa.ForeignKeyConstraint(["financial_transaction_id"], ["uber_financial_transactions.id"]),
        sa.ForeignKeyConstraint(["provider_draft_id"], ["email_provider_drafts.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("financial_transaction_id"),
    )
    op.create_index("ix_customer_refund_disputes_claim_order_id", "uber_customer_refund_disputes", ["claim_order_id"])
    op.create_index("ix_customer_refund_disputes_deducted_at", "uber_customer_refund_disputes", ["deducted_at"])
    op.create_index("ix_customer_refund_disputes_dispute_type", "uber_customer_refund_disputes", ["dispute_type"])
    op.create_index("ix_customer_refund_disputes_evidence_status", "uber_customer_refund_disputes", ["evidence_status"])
    op.create_index(
        "ix_customer_refund_disputes_financial_transaction_id",
        "uber_customer_refund_disputes",
        ["financial_transaction_id"],
    )
    op.create_index("ix_customer_refund_disputes_restaurant_id", "uber_customer_refund_disputes", ["restaurant_id"])
    op.create_index("ix_customer_refund_disputes_status", "uber_customer_refund_disputes", ["status"])

    op.create_table(
        "customer_refund_evidence_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dispute_id", sa.Integer(), nullable=False),
        sa.Column("required_evidence_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("evidence_file_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(NEW_REQUIRED_EVIDENCE_CHECK, name="ck_customer_refund_requirements_evidence_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'uploaded', 'waived', 'not_available')",
            name="ck_customer_refund_requirements_status",
        ),
        sa.ForeignKeyConstraint(["dispute_id"], ["uber_customer_refund_disputes.id"]),
        sa.ForeignKeyConstraint(["evidence_file_id"], ["evidence_files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dispute_id", "required_evidence_type", name="uq_customer_refund_requirement_type"),
    )
    op.create_index("ix_customer_refund_requirements_dispute_id", "customer_refund_evidence_requirements", ["dispute_id"])
    op.create_index("ix_customer_refund_requirements_status", "customer_refund_evidence_requirements", ["status"])

    with op.batch_alter_table("evidence_request_tasks", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_evidence_request_tasks_required_type", type_="check")
        batch_op.add_column(sa.Column("customer_refund_dispute_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evidence_request_tasks_customer_refund_dispute_id",
            "uber_customer_refund_disputes",
            ["customer_refund_dispute_id"],
            ["id"],
        )
        batch_op.create_check_constraint("ck_evidence_request_tasks_required_type", NEW_REQUIRED_EVIDENCE_CHECK)
    op.create_index(
        "ix_evidence_request_tasks_customer_refund_dispute_id",
        "evidence_request_tasks",
        ["customer_refund_dispute_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_request_tasks_customer_refund_dispute_id", table_name="evidence_request_tasks")
    op.execute(
        "UPDATE evidence_request_tasks SET required_evidence_type = 'other' WHERE required_evidence_type NOT IN "
        "('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', 'uber_screenshot', 'other')"
    )
    with op.batch_alter_table("evidence_request_tasks", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("fk_evidence_request_tasks_customer_refund_dispute_id", type_="foreignkey")
        batch_op.drop_constraint("ck_evidence_request_tasks_required_type", type_="check")
        batch_op.drop_column("customer_refund_dispute_id")
        batch_op.create_check_constraint("ck_evidence_request_tasks_required_type", OLD_REQUIRED_EVIDENCE_CHECK)

    op.drop_index("ix_customer_refund_requirements_status", table_name="customer_refund_evidence_requirements")
    op.drop_index("ix_customer_refund_requirements_dispute_id", table_name="customer_refund_evidence_requirements")
    op.drop_table("customer_refund_evidence_requirements")
    op.drop_index("ix_customer_refund_disputes_status", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_restaurant_id", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_financial_transaction_id", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_evidence_status", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_dispute_type", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_deducted_at", table_name="uber_customer_refund_disputes")
    op.drop_index("ix_customer_refund_disputes_claim_order_id", table_name="uber_customer_refund_disputes")
    op.drop_table("uber_customer_refund_disputes")

    op.execute("UPDATE email_drafts SET draft_type = 'proof_reply' WHERE draft_type LIKE 'customer_refund_%'")
    with op.batch_alter_table("email_drafts", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_email_drafts_type", type_="check")
        batch_op.create_check_constraint("ck_email_drafts_type", OLD_EMAIL_DRAFT_TYPE_CHECK)

    op.execute(
        "UPDATE evidence_files SET evidence_type = 'other' WHERE evidence_type NOT IN "
        "('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', 'uber_screenshot', 'other')"
    )
    with op.batch_alter_table("evidence_files", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_evidence_files_type", type_="check")
        batch_op.create_check_constraint("ck_evidence_files_type", OLD_EVIDENCE_CHECK)
