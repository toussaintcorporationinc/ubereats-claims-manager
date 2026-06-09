"""bulk evidence imports and persistent appeals

Revision ID: 0018_evidence_appeals
Revises: 0017_refund_reviews
Create Date: 2026-06-09 20:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_evidence_appeals"
down_revision: str | None = "0017_refund_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EMAIL_DRAFT_TYPE_CHECK = (
    "draft_type IN ('initial_claim', 'followup_1', 'followup_2', 'escalation', 'proof_reply', "
    "'customer_refund_order_not_received', 'customer_refund_missing_item', "
    "'customer_refund_order_error_adjustment', 'customer_refund_generic')"
)
NEW_EMAIL_DRAFT_TYPE_CHECK = (
    "draft_type IN ('initial_claim', 'followup_1', 'followup_2', 'escalation', 'proof_reply', "
    "'customer_refund_order_not_received', 'customer_refund_missing_item', "
    "'customer_refund_order_error_adjustment', 'customer_refund_generic', "
    "'appeal_generic_refusal', 'appeal_missing_evidence_reply', "
    "'appeal_order_prepared_before_cancellation', 'appeal_order_not_received_delivery_proof', "
    "'appeal_missing_item_preparation_proof', 'appeal_escalation', 'appeal_payment_verification')"
)


def _batch_recreate_mode() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    with op.batch_alter_table("email_drafts", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_email_drafts_type", type_="check")
        batch_op.create_check_constraint("ck_email_drafts_type", NEW_EMAIL_DRAFT_TYPE_CHECK)

    op.create_table(
        "evidence_import_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stored_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analyzed_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('multi_file_upload', 'zip_upload', 'mobile_upload', 'server_folder_import')",
            name="ck_evidence_import_batches_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'extracting', 'stored', 'analyzing', 'analyzed', 'partially_analyzed', 'failed', 'cancelled')",
            name="ck_evidence_import_batches_status",
        ),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_import_batches_uploaded_by_user_id", "evidence_import_batches", ["uploaded_by_user_id"])
    op.create_index("ix_evidence_import_batches_restaurant_id", "evidence_import_batches", ["restaurant_id"])
    op.create_index("ix_evidence_import_batches_status", "evidence_import_batches", ["status"])

    op.create_table(
        "evidence_imported_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("internal_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_backend", sa.String(length=50), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('stored', 'analysis_pending', 'analyzed', 'failed', 'ignored')",
            name="ck_evidence_imported_files_status",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["evidence_import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_imported_files_batch_id", "evidence_imported_files", ["batch_id"])
    op.create_index("ix_evidence_imported_files_uploaded_by_user_id", "evidence_imported_files", ["uploaded_by_user_id"])
    op.create_index("ix_evidence_imported_files_status", "evidence_imported_files", ["status"])
    op.create_index("ix_evidence_imported_files_checksum_sha256", "evidence_imported_files", ["checksum_sha256"])

    op.create_table(
        "evidence_analysis_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("imported_file_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("detected_evidence_type", sa.String(length=50), nullable=False),
        sa.Column("detected_restaurant_name", sa.String(length=255), nullable=True),
        sa.Column("detected_uber_order_number", sa.String(length=255), nullable=True),
        sa.Column("detected_display_id", sa.String(length=255), nullable=True),
        sa.Column("detected_order_date", sa.Date(), nullable=True),
        sa.Column("detected_order_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("detected_currency", sa.String(length=3), nullable=True),
        sa.Column("detected_keywords_json", sa.JSON(), nullable=True),
        sa.Column("classification_confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("extraction_confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("matching_confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("raw_result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('local_ocr', 'openai_vision', 'fake')", name="ck_evidence_analysis_results_provider"),
        sa.CheckConstraint("status IN ('success', 'partial', 'failed', 'manual_review')", name="ck_evidence_analysis_results_status"),
        sa.CheckConstraint(
            "detected_evidence_type IN ('receipt', 'cancellation_proof', 'preparation_proof', 'waste_photo', "
            "'uber_screenshot', 'delivery_proof', 'packaging_photo', 'sealed_bag_photo', 'courier_statement', "
            "'gps_or_route_proof', 'customer_contact_proof', 'order_details_screenshot', 'other', 'unknown')",
            name="ck_evidence_analysis_results_type",
        ),
        sa.ForeignKeyConstraint(["imported_file_id"], ["evidence_imported_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_analysis_results_imported_file_id", "evidence_analysis_results", ["imported_file_id"])
    op.create_index("ix_evidence_analysis_results_status", "evidence_analysis_results", ["status"])
    op.create_index("ix_evidence_analysis_results_detected_type", "evidence_analysis_results", ["detected_evidence_type"])

    op.create_table(
        "evidence_match_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("imported_file_id", sa.Integer(), nullable=False),
        sa.Column("analysis_result_id", sa.Integer(), nullable=False),
        sa.Column("candidate_type", sa.String(length=50), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("match_reason", sa.String(length=100), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "candidate_type IN ('claim_order', 'evidence_task', 'customer_refund_dispute', 'reconciliation_result')",
            name="ck_evidence_match_candidates_type",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'auto_attached', 'accepted', 'rejected', 'manual_review')",
            name="ck_evidence_match_candidates_status",
        ),
        sa.CheckConstraint(
            "match_reason IN ('exact_order_number', 'display_id_match', 'amount_date_restaurant_match', "
            "'restaurant_date_amount_match', 'evidence_task_type_match', 'filename_hint', 'manual_selection', "
            "'low_confidence', 'ambiguous_candidates')",
            name="ck_evidence_match_candidates_reason",
        ),
        sa.ForeignKeyConstraint(["analysis_result_id"], ["evidence_analysis_results.id"]),
        sa.ForeignKeyConstraint(["imported_file_id"], ["evidence_imported_files.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_match_candidates_imported_file_id", "evidence_match_candidates", ["imported_file_id"])
    op.create_index("ix_evidence_match_candidates_analysis_result_id", "evidence_match_candidates", ["analysis_result_id"])
    op.create_index("ix_evidence_match_candidates_candidate", "evidence_match_candidates", ["candidate_type", "candidate_id"])
    op.create_index("ix_evidence_match_candidates_restaurant_id", "evidence_match_candidates", ["restaurant_id"])
    op.create_index("ix_evidence_match_candidates_status", "evidence_match_candidates", ["status"])

    op.create_table(
        "evidence_attachment_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("imported_file_id", sa.Integer(), nullable=False),
        sa.Column("evidence_file_id", sa.Integer(), nullable=True),
        sa.Column("candidate_type", sa.String(length=50), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "candidate_type IN ('claim_order', 'evidence_task', 'customer_refund_dispute', 'reconciliation_result')",
            name="ck_evidence_attachment_decisions_type",
        ),
        sa.CheckConstraint("decision IN ('attached', 'rejected', 'ignored', 'deferred')", name="ck_evidence_attachment_decisions_decision"),
        sa.ForeignKeyConstraint(["evidence_file_id"], ["evidence_files.id"]),
        sa.ForeignKeyConstraint(["imported_file_id"], ["evidence_imported_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_attachment_decisions_imported_file_id", "evidence_attachment_decisions", ["imported_file_id"])
    op.create_index("ix_evidence_attachment_decisions_evidence_file_id", "evidence_attachment_decisions", ["evidence_file_id"])
    op.create_index("ix_evidence_attachment_decisions_candidate", "evidence_attachment_decisions", ["candidate_type", "candidate_id"])

    op.create_table(
        "appeal_workflows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_type", sa.String(length=50), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("claim_order_id", sa.Integer(), nullable=True),
        sa.Column("customer_refund_dispute_id", sa.Integer(), nullable=True),
        sa.Column("reconciliation_result_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refusal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("appeal_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_refusal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_appeal_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_action_type", sa.String(length=50), nullable=True),
        sa.Column("opened_by_user_id", sa.Integer(), nullable=True),
        sa.Column("manually_closed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("manually_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_close_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("case_type IN ('claim_order', 'customer_refund_dispute', 'reconciliation_result')", name="ck_appeal_workflows_case_type"),
        sa.CheckConstraint(
            "status IN ('active', 'appeal_needed', 'evidence_needed', 'draft_needed', 'gmail_draft_needed', "
            "'appeal_sent', 'response_received', 'escalated', 'payment_to_verify', 'payment_confirmed', "
            "'accepted', 'paused', 'manually_closed')",
            name="ck_appeal_workflows_status",
        ),
        sa.CheckConstraint(
            "next_action_type IN ('review_refusal', 'request_more_evidence', 'create_appeal_draft', "
            "'create_gmail_draft', 'send_manual_appeal', 'escalation', 'payment_verification', 'manual_review')",
            name="ck_appeal_workflows_next_action_type",
        ),
        sa.ForeignKeyConstraint(["claim_order_id"], ["claim_orders.id"]),
        sa.ForeignKeyConstraint(["customer_refund_dispute_id"], ["uber_customer_refund_disputes.id"]),
        sa.ForeignKeyConstraint(["reconciliation_result_id"], ["uber_reconciliation_results.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_type", "case_id", name="uq_appeal_workflows_case"),
    )
    op.create_index("ix_appeal_workflows_restaurant_id", "appeal_workflows", ["restaurant_id"])
    op.create_index("ix_appeal_workflows_status", "appeal_workflows", ["status"])
    op.create_index("ix_appeal_workflows_next_action_type", "appeal_workflows", ["next_action_type"])
    op.create_index("ix_appeal_workflows_claim_order_id", "appeal_workflows", ["claim_order_id"])
    op.create_index("ix_appeal_workflows_customer_refund_dispute_id", "appeal_workflows", ["customer_refund_dispute_id"])
    op.create_index("ix_appeal_workflows_reconciliation_result_id", "appeal_workflows", ["reconciliation_result_id"])

    op.create_table(
        "appeal_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("appeal_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("based_on_refusal_message_id", sa.Integer(), nullable=True),
        sa.Column("email_draft_id", sa.Integer(), nullable=True),
        sa.Column("provider_draft_id", sa.Integer(), nullable=True),
        sa.Column("sent_email_thread_id", sa.Integer(), nullable=True),
        sa.Column("argument_summary", sa.Text(), nullable=True),
        sa.Column("new_evidence_summary", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "appeal_type IN ('first_appeal', 'second_appeal', 'escalation', 'payment_verification', 'evidence_reply', 'manager_review')",
            name="ck_appeal_attempts_type",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'draft_created', 'gmail_draft_created', 'sent', 'response_received', 'superseded', 'cancelled')",
            name="ck_appeal_attempts_status",
        ),
        sa.ForeignKeyConstraint(["based_on_refusal_message_id"], ["inbound_email_messages.id"]),
        sa.ForeignKeyConstraint(["email_draft_id"], ["email_drafts.id"]),
        sa.ForeignKeyConstraint(["provider_draft_id"], ["email_provider_drafts.id"]),
        sa.ForeignKeyConstraint(["sent_email_thread_id"], ["email_threads.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["appeal_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "attempt_number", name="uq_appeal_attempts_number"),
    )
    op.create_index("ix_appeal_attempts_workflow_id", "appeal_attempts", ["workflow_id"])
    op.create_index("ix_appeal_attempts_status", "appeal_attempts", ["status"])
    op.create_index("ix_appeal_attempts_email_draft_id", "appeal_attempts", ["email_draft_id"])
    op.create_index("ix_appeal_attempts_provider_draft_id", "appeal_attempts", ["provider_draft_id"])

    op.create_table(
        "refusal_analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Integer(), nullable=True),
        sa.Column("review_id", sa.Integer(), nullable=True),
        sa.Column("refusal_source", sa.String(length=50), nullable=False),
        sa.Column("refusal_reason", sa.String(length=255), nullable=False),
        sa.Column("refusal_text_excerpt", sa.Text(), nullable=True),
        sa.Column("recommended_next_action", sa.String(length=50), nullable=False),
        sa.Column("required_evidence_types_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "refusal_source IN ('claim_response_review', 'customer_refund_review', 'inbound_message', 'manual')",
            name="ck_refusal_analyses_source",
        ),
        sa.CheckConstraint(
            "recommended_next_action IN ('provide_missing_evidence', 'clarify_order_prepared', "
            "'clarify_delivery_proof', 'challenge_generic_refusal', 'request_escalation', "
            "'payment_verification', 'manual_review')",
            name="ck_refusal_analyses_next_action",
        ),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_email_messages.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["appeal_workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refusal_analyses_workflow_id", "refusal_analyses", ["workflow_id"])
    op.create_index("ix_refusal_analyses_inbound_message_id", "refusal_analyses", ["inbound_message_id"])
    op.create_index("ix_refusal_analyses_review_id", "refusal_analyses", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_refusal_analyses_review_id", table_name="refusal_analyses")
    op.drop_index("ix_refusal_analyses_inbound_message_id", table_name="refusal_analyses")
    op.drop_index("ix_refusal_analyses_workflow_id", table_name="refusal_analyses")
    op.drop_table("refusal_analyses")
    op.drop_index("ix_appeal_attempts_provider_draft_id", table_name="appeal_attempts")
    op.drop_index("ix_appeal_attempts_email_draft_id", table_name="appeal_attempts")
    op.drop_index("ix_appeal_attempts_status", table_name="appeal_attempts")
    op.drop_index("ix_appeal_attempts_workflow_id", table_name="appeal_attempts")
    op.drop_table("appeal_attempts")
    op.drop_index("ix_appeal_workflows_reconciliation_result_id", table_name="appeal_workflows")
    op.drop_index("ix_appeal_workflows_customer_refund_dispute_id", table_name="appeal_workflows")
    op.drop_index("ix_appeal_workflows_claim_order_id", table_name="appeal_workflows")
    op.drop_index("ix_appeal_workflows_next_action_type", table_name="appeal_workflows")
    op.drop_index("ix_appeal_workflows_status", table_name="appeal_workflows")
    op.drop_index("ix_appeal_workflows_restaurant_id", table_name="appeal_workflows")
    op.drop_table("appeal_workflows")
    op.drop_index("ix_evidence_attachment_decisions_candidate", table_name="evidence_attachment_decisions")
    op.drop_index("ix_evidence_attachment_decisions_evidence_file_id", table_name="evidence_attachment_decisions")
    op.drop_index("ix_evidence_attachment_decisions_imported_file_id", table_name="evidence_attachment_decisions")
    op.drop_table("evidence_attachment_decisions")
    op.drop_index("ix_evidence_match_candidates_status", table_name="evidence_match_candidates")
    op.drop_index("ix_evidence_match_candidates_restaurant_id", table_name="evidence_match_candidates")
    op.drop_index("ix_evidence_match_candidates_candidate", table_name="evidence_match_candidates")
    op.drop_index("ix_evidence_match_candidates_analysis_result_id", table_name="evidence_match_candidates")
    op.drop_index("ix_evidence_match_candidates_imported_file_id", table_name="evidence_match_candidates")
    op.drop_table("evidence_match_candidates")
    op.drop_index("ix_evidence_analysis_results_detected_type", table_name="evidence_analysis_results")
    op.drop_index("ix_evidence_analysis_results_status", table_name="evidence_analysis_results")
    op.drop_index("ix_evidence_analysis_results_imported_file_id", table_name="evidence_analysis_results")
    op.drop_table("evidence_analysis_results")
    op.drop_index("ix_evidence_imported_files_checksum_sha256", table_name="evidence_imported_files")
    op.drop_index("ix_evidence_imported_files_status", table_name="evidence_imported_files")
    op.drop_index("ix_evidence_imported_files_uploaded_by_user_id", table_name="evidence_imported_files")
    op.drop_index("ix_evidence_imported_files_batch_id", table_name="evidence_imported_files")
    op.drop_table("evidence_imported_files")
    op.drop_index("ix_evidence_import_batches_status", table_name="evidence_import_batches")
    op.drop_index("ix_evidence_import_batches_restaurant_id", table_name="evidence_import_batches")
    op.drop_index("ix_evidence_import_batches_uploaded_by_user_id", table_name="evidence_import_batches")
    op.drop_table("evidence_import_batches")
    op.execute("UPDATE email_drafts SET draft_type = 'proof_reply' WHERE draft_type LIKE 'appeal_%'")
    with op.batch_alter_table("email_drafts", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_constraint("ck_email_drafts_type", type_="check")
        batch_op.create_check_constraint("ck_email_drafts_type", OLD_EMAIL_DRAFT_TYPE_CHECK)
