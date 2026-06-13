from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

CLAIM_ORDER_STATUSES = (
    "draft",
    "missing_evidence",
    "ready_to_send",
    "draft_email_created",
    "sent",
    "waiting_uber_response",
    "response_received",
    "followup_1_sent",
    "followup_2_sent",
    "escalation_sent",
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "manual_review",
    "closed",
)

EVIDENCE_TYPES = (
    "receipt",
    "cancellation_proof",
    "preparation_proof",
    "waste_photo",
    "uber_screenshot",
    "delivery_proof",
    "packaging_photo",
    "sealed_bag_photo",
    "courier_statement",
    "gps_or_route_proof",
    "customer_contact_proof",
    "order_details_screenshot",
    "other",
)

EMAIL_DRAFT_TYPES = (
    "initial_claim",
    "followup_1",
    "followup_2",
    "escalation",
    "proof_reply",
    "customer_refund_order_not_received",
    "customer_refund_missing_item",
    "customer_refund_order_error_adjustment",
    "customer_refund_generic",
    "appeal_generic_refusal",
    "appeal_missing_evidence_reply",
    "appeal_order_prepared_before_cancellation",
    "appeal_order_not_received_delivery_proof",
    "appeal_missing_item_preparation_proof",
    "appeal_escalation",
    "appeal_payment_verification",
)

EMAIL_DRAFT_STATUSES = ("created", "draft", "ready", "archived")
EMAIL_DIRECTIONS = ("inbound", "outbound")
EMAIL_PROVIDERS = ("internal", "gmail", "resend", "microsoft_graph")
USER_ROLES = ("owner", "manager", "staff")
IMPORT_BATCH_STATUSES = ("uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled")
IMPORT_ROW_STATUSES = ("valid", "invalid", "duplicate", "unauthorized", "created", "skipped")
EMAIL_ACCOUNT_PROVIDERS = ("gmail",)
EMAIL_PROVIDER_DRAFT_PROVIDERS = ("gmail", "resend")
EMAIL_PROVIDER_DRAFT_STATUSES = ("provider_draft_created", "send_requested", "sent", "failed")
GMAIL_SYNC_STATUSES = ("idle", "running", "success", "failed")
INBOUND_EMAIL_MATCH_STATUSES = ("linked", "unlinked", "ignored")
INBOUND_EMAIL_MATCH_REASONS = (
    "thread_id_match",
    "order_number_match",
    "subject_match",
    "manual_link",
    "no_match",
    "ignored_sender",
)
INBOUND_EMAIL_REVIEW_STATUSES = ("unreviewed", "reviewed", "ignored")
GMAIL_RESPONSE_ANALYSIS_STATUSES = ("analyzed", "applied", "manual_review", "ignored", "failed")
CLAIM_RESPONSE_REVIEW_TYPES = (
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "evidence_requested",
    "information_requested",
    "followup_needed",
    "ignored",
    "manual_review",
)
CUSTOMER_REFUND_REVIEW_TYPES = CLAIM_RESPONSE_REVIEW_TYPES
FOLLOWUP_TASK_TYPES = ("followup_1", "followup_2", "escalation", "manual_review", "payment_verification")
FOLLOWUP_TASK_STATUSES = (
    "pending",
    "draft_created",
    "provider_draft_created",
    "completed",
    "skipped",
    "cancelled",
)
EVIDENCE_REQUEST_TASK_TYPES = (
    "missing_receipt",
    "missing_cancellation_proof",
    "missing_preparation_proof",
    "missing_waste_photo",
    "missing_uber_screenshot",
    "evidence_review",
)
EVIDENCE_REQUEST_TASK_STATUSES = ("pending", "uploaded", "completed", "skipped", "cancelled")
EVIDENCE_REQUEST_PRIORITIES = ("low", "normal", "high", "urgent")
CUSTOMER_REFUND_DISPUTE_TYPES = (
    "order_not_received",
    "missing_item",
    "incorrect_item",
    "damaged_order",
    "quality_issue",
    "customer_refund",
    "order_error_adjustment",
    "chargeback",
    "unknown",
)
CUSTOMER_REFUND_DISPUTE_REASONS = (
    "customer_reported_not_received",
    "customer_reported_missing_item",
    "customer_reported_wrong_item",
    "customer_reported_quality_issue",
    "uber_adjustment_order_error",
    "refund_without_sufficient_proof",
    "self_delivery_dispute",
    "unknown_reason",
)
CUSTOMER_REFUND_DISPUTE_STATUSES = (
    "detected",
    "needs_evidence",
    "evidence_ready",
    "draft_created",
    "gmail_draft_created",
    "sent",
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "ignored",
    "manual_review",
)
CUSTOMER_REFUND_EVIDENCE_STATUSES = ("missing", "partial", "complete", "not_required", "manual_review")
CUSTOMER_REFUND_REQUIREMENT_STATUSES = ("pending", "uploaded", "waived", "not_available")
UBER_INTEGRATION_PROVIDERS = ("uber_eats",)
UBER_INTEGRATION_STATUSES = ("not_configured", "pending_approval", "connected", "disconnected", "disabled")
UBER_SNAPSHOT_SOURCES = ("api_orders", "api_reporting", "manager_export")
UBER_RECONCILIATION_STATUSES = (
    "compensated",
    "not_compensated",
    "partially_compensated",
    "needs_evidence",
    "already_claimed",
    "ignored",
    "manual_review",
)
UBER_RECONCILIATION_FINANCIAL_STATUSES = (
    "compensated",
    "not_compensated",
    "partially_compensated",
    "manual_review",
    "not_cancelled",
)
UBER_RECONCILIATION_RUN_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
UBER_REPORTING_IMPORT_REPORT_TYPES = ("orders_report", "payments_report", "adjustments_report", "combined_report")
UBER_REPORTING_IMPORT_BATCH_STATUSES = ("uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled")
UBER_REPORTING_IMPORT_ROW_STATUSES = ("valid", "invalid", "warning", "duplicate", "created", "skipped")
EVIDENCE_IMPORT_SOURCE_TYPES = ("multi_file_upload", "zip_upload", "mobile_upload", "server_folder_import")
EVIDENCE_IMPORT_BATCH_STATUSES = (
    "uploaded",
    "extracting",
    "stored",
    "analyzing",
    "analyzed",
    "partially_analyzed",
    "failed",
    "cancelled",
)
EVIDENCE_IMPORTED_FILE_STATUSES = ("stored", "analysis_pending", "analyzed", "failed", "ignored")
EVIDENCE_ANALYSIS_PROVIDERS = ("local_ocr", "openai_vision", "fake")
EVIDENCE_ANALYSIS_STATUSES = ("success", "partial", "failed", "manual_review")
EVIDENCE_ANALYSIS_TYPES = (*EVIDENCE_TYPES, "unknown")
EVIDENCE_MATCH_CANDIDATE_TYPES = ("claim_order", "evidence_task", "customer_refund_dispute", "reconciliation_result")
EVIDENCE_MATCH_STATUSES = ("proposed", "auto_attached", "accepted", "rejected", "manual_review")
EVIDENCE_MATCH_REASONS = (
    "exact_order_number",
    "display_id_match",
    "amount_date_restaurant_match",
    "restaurant_date_amount_match",
    "evidence_task_type_match",
    "filename_hint",
    "manual_selection",
    "low_confidence",
    "ambiguous_candidates",
)
EVIDENCE_ATTACHMENT_DECISIONS = ("attached", "rejected", "ignored", "deferred")
APPEAL_CASE_TYPES = ("claim_order", "customer_refund_dispute", "reconciliation_result")
APPEAL_WORKFLOW_STATUSES = (
    "active",
    "appeal_needed",
    "evidence_needed",
    "draft_needed",
    "gmail_draft_needed",
    "appeal_sent",
    "response_received",
    "escalated",
    "payment_to_verify",
    "payment_confirmed",
    "accepted",
    "paused",
    "manually_closed",
)
APPEAL_NEXT_ACTION_TYPES = (
    "review_refusal",
    "request_more_evidence",
    "create_appeal_draft",
    "create_gmail_draft",
    "send_manual_appeal",
    "escalation",
    "payment_verification",
    "manual_review",
)
APPEAL_TYPES = (
    "first_appeal",
    "second_appeal",
    "escalation",
    "payment_verification",
    "evidence_reply",
    "manager_review",
)
APPEAL_ATTEMPT_STATUSES = (
    "planned",
    "draft_created",
    "gmail_draft_created",
    "sent",
    "response_received",
    "superseded",
    "cancelled",
)
REFUSAL_SOURCES = ("claim_response_review", "customer_refund_review", "inbound_message", "manual")
REFUSAL_NEXT_ACTIONS = (
    "provide_missing_evidence",
    "clarify_order_prepared",
    "clarify_delivery_proof",
    "challenge_generic_refusal",
    "request_escalation",
    "payment_verification",
    "manual_review",
)
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
SMART_IMPORT_PREVIEW_STATUSES = ("previewed", "confirmed", "cancelled", "expired")
SMART_IMPORT_FILE_CATEGORIES = ("uber_reporting", "evidence", "zip", "unknown")
SMART_IMPORT_RECOMMENDED_ACTIONS = (
    "import_uber_reporting",
    "import_evidence_bulk",
    "manual_review",
    "ignore",
)
SMART_IMPORT_FILE_STATUSES = ("previewed", "confirmed", "routed", "ignored", "failed", "expired", "manual_review")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def check_in_constraint(column_name: str, allowed_values: tuple[str, ...]) -> str:
    quoted_values = ", ".join(f"'{value}'" for value in allowed_values)
    return f"{column_name} IN ({quoted_values})"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(check_in_constraint("role", USER_ROLES), name="ck_users_role"),
        Index("ix_users_email", "email", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(500), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    restaurant_access: Mapped[list["UserRestaurantAccess"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserRestaurantAccess(Base):
    __tablename__ = "user_restaurant_access"
    __table_args__ = (
        UniqueConstraint("user_id", "restaurant_id", name="uq_user_restaurant_access"),
        Index("ix_user_restaurant_access_user_id", "user_id"),
        Index("ix_user_restaurant_access_restaurant_id", "restaurant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    user: Mapped[User] = relationship(back_populates="restaurant_access")
    restaurant: Mapped["Restaurant"] = relationship(back_populates="user_access")


class Restaurant(TimestampMixin, Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    uber_merchant_id: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    autopilot_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    orders: Mapped[list["ClaimOrder"]] = relationship(back_populates="restaurant")
    user_access: Mapped[list[UserRestaurantAccess]] = relationship(back_populates="restaurant")
    uber_store_mappings: Mapped[list["UberStoreMapping"]] = relationship(back_populates="restaurant")
    uber_order_snapshots: Mapped[list["UberOrderSnapshot"]] = relationship(back_populates="restaurant")
    uber_financial_transactions: Mapped[list["UberFinancialTransaction"]] = relationship(back_populates="restaurant")
    uber_reconciliation_results: Mapped[list["UberReconciliationResult"]] = relationship(back_populates="restaurant")
    uber_reconciliation_runs: Mapped[list["UberReconciliationRun"]] = relationship(back_populates="restaurant")
    evidence_request_tasks: Mapped[list["EvidenceRequestTask"]] = relationship(back_populates="restaurant")
    customer_refund_disputes: Mapped[list["UberCustomerRefundDispute"]] = relationship(back_populates="restaurant")
    evidence_import_batches: Mapped[list["EvidenceImportBatch"]] = relationship(back_populates="restaurant")
    appeal_workflows: Mapped[list["AppealWorkflow"]] = relationship(back_populates="restaurant")
    autopilot_actions: Mapped[list["AutopilotAction"]] = relationship(back_populates="restaurant")
    email_account_mapping: Mapped["EmailAccountRestaurantMapping | None"] = relationship(
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )


class ClaimOrder(TimestampMixin, Base):
    __tablename__ = "claim_orders"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "uber_order_number", name="uq_claim_orders_restaurant_uber_order"),
        CheckConstraint(check_in_constraint("status", CLAIM_ORDER_STATUSES), name="ck_claim_orders_status"),
        Index("ix_claim_orders_restaurant_id", "restaurant_id"),
        Index("ix_claim_orders_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    internal_reference: Mapped[str | None] = mapped_column(String(255))
    uber_order_number: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255))
    order_date: Mapped[date | None] = mapped_column(Date)
    order_time: Mapped[time | None] = mapped_column(Time)
    cancellation_time: Mapped[time | None] = mapped_column(Time)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    accepted_by_restaurant: Mapped[bool | None] = mapped_column(Boolean)
    prepared_before_cancellation: Mapped[bool | None] = mapped_column(Boolean)
    loss_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(100))
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)

    restaurant: Mapped[Restaurant] = relationship(back_populates="orders")
    evidence_files: Mapped[list["EvidenceFile"]] = relationship(back_populates="order")
    email_drafts: Mapped[list["EmailDraft"]] = relationship(back_populates="order")
    email_threads: Mapped[list["EmailThread"]] = relationship(back_populates="order")
    inbound_email_messages: Mapped[list["InboundEmailMessage"]] = relationship(back_populates="order")
    response_reviews: Mapped[list["ClaimResponseReview"]] = relationship(back_populates="order")
    followup_tasks: Mapped[list["FollowUpTask"]] = relationship(back_populates="order")
    evidence_request_tasks: Mapped[list["EvidenceRequestTask"]] = relationship(back_populates="order")
    customer_refund_disputes: Mapped[list["UberCustomerRefundDispute"]] = relationship(back_populates="claim_order")
    appeal_workflows: Mapped[list["AppealWorkflow"]] = relationship(back_populates="claim_order")


class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    __table_args__ = (
        CheckConstraint(check_in_constraint("evidence_type", EVIDENCE_TYPES), name="ck_evidence_files_type"),
        Index("ix_evidence_files_order_id", "order_id"),
        Index("ix_evidence_files_uploaded_by_user_id", "uploaded_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[ClaimOrder] = relationship(back_populates="evidence_files")
    attachment_decisions: Mapped[list["EvidenceAttachmentDecision"]] = relationship(back_populates="evidence_file")

    @property
    def download_url(self) -> str | None:
        if self.deleted_at is not None or not self.checksum_sha256:
            return None
        return f"/v1/evidence/{self.id}/download"


class EmailDraft(TimestampMixin, Base):
    __tablename__ = "email_drafts"
    __table_args__ = (
        CheckConstraint(check_in_constraint("draft_type", EMAIL_DRAFT_TYPES), name="ck_email_drafts_type"),
        CheckConstraint(check_in_constraint("status", EMAIL_DRAFT_STATUSES), name="ck_email_drafts_status"),
        Index("ix_email_drafts_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    draft_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    order: Mapped[ClaimOrder] = relationship(back_populates="email_drafts")
    provider_drafts: Mapped[list["EmailProviderDraft"]] = relationship(back_populates="email_draft")

    @property
    def latest_provider_draft(self) -> "EmailProviderDraft | None":
        if not self.provider_drafts:
            return None
        return sorted(self.provider_drafts, key=lambda item: item.id)[-1]

    @property
    def provider_draft_id(self) -> str | None:
        latest = self.latest_provider_draft
        return latest.provider_draft_id if latest else None

    @property
    def provider_message_id(self) -> str | None:
        latest = self.latest_provider_draft
        return latest.provider_message_id if latest else None

    @property
    def provider_sent_at(self) -> datetime | None:
        latest = self.latest_provider_draft
        return latest.sent_at if latest else None

    @property
    def provider_to_email(self) -> str | None:
        latest = self.latest_provider_draft
        return latest.to_email if latest else None

    @property
    def provider_status(self) -> str | None:
        latest = self.latest_provider_draft
        return latest.status if latest else None

    @property
    def provider(self) -> str | None:
        latest = self.latest_provider_draft
        return latest.provider if latest else None


class EmailThread(Base):
    __tablename__ = "email_threads"
    __table_args__ = (
        CheckConstraint(check_in_constraint("provider", EMAIL_PROVIDERS), name="ck_email_threads_provider"),
        CheckConstraint(check_in_constraint("direction", EMAIL_DIRECTIONS), name="ck_email_threads_direction"),
        Index("ix_email_threads_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    thread_id: Mapped[str | None] = mapped_column(String(255))
    message_id: Mapped[str | None] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    ai_classification: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    order: Mapped[ClaimOrder] = relationship(back_populates="email_threads")


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(check_in_constraint("status", IMPORT_BATCH_STATUSES), name="ck_import_batches_status"),
        Index("ix_import_batches_status", "status"),
        Index("ix_import_batches_uploaded_by_user_id", "uploaded_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unauthorized_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    @property
    def batch_id(self) -> int:
        return self.id


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint(check_in_constraint("status", IMPORT_ROW_STATUSES), name="ck_import_rows_status"),
        Index("ix_import_rows_batch_id", "batch_id"),
        Index("ix_import_rows_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_order_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")


class EmailAccount(TimestampMixin, Base):
    __tablename__ = "email_accounts"
    __table_args__ = (
        CheckConstraint(check_in_constraint("provider", EMAIL_ACCOUNT_PROVIDERS), name="ck_email_accounts_provider"),
        Index("ix_email_accounts_user_provider", "user_id", "provider"),
        Index("ix_email_accounts_provider_email", "provider", "email_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    email_address: Mapped[str | None] = mapped_column(String(255))
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sync_state: Mapped["GmailSyncState | None"] = relationship(
        back_populates="email_account",
        cascade="all, delete-orphan",
    )
    inbound_messages: Mapped[list["InboundEmailMessage"]] = relationship(back_populates="email_account")
    restaurant_mappings: Mapped[list["EmailAccountRestaurantMapping"]] = relationship(
        back_populates="email_account",
        cascade="all, delete-orphan",
    )


class EmailAccountRestaurantMapping(TimestampMixin, Base):
    __tablename__ = "email_account_restaurant_mappings"
    __table_args__ = (
        UniqueConstraint("restaurant_id", name="uq_email_account_restaurant_mapping_restaurant"),
        Index("ix_email_account_restaurant_mappings_email_account_id", "email_account_id"),
        Index("ix_email_account_restaurant_mappings_restaurant_id", "restaurant_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    restaurant: Mapped[Restaurant] = relationship(back_populates="email_account_mapping")
    email_account: Mapped[EmailAccount] = relationship(back_populates="restaurant_mappings")


class GmailSyncState(TimestampMixin, Base):
    __tablename__ = "gmail_sync_states"
    __table_args__ = (
        CheckConstraint(check_in_constraint("status", GMAIL_SYNC_STATUSES), name="ck_gmail_sync_states_status"),
        Index("ix_gmail_sync_states_email_account_id", "email_account_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), nullable=False)
    last_history_id: Mapped[str | None] = mapped_column(String(255))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")
    last_error: Mapped[str | None] = mapped_column(Text)

    email_account: Mapped[EmailAccount] = relationship(back_populates="sync_state")


class InboundEmailMessage(TimestampMixin, Base):
    __tablename__ = "inbound_email_messages"
    __table_args__ = (
        UniqueConstraint(
            "email_account_id",
            "provider_message_id",
            name="uq_inbound_email_messages_account_message",
        ),
        CheckConstraint(check_in_constraint("provider", EMAIL_ACCOUNT_PROVIDERS), name="ck_inbound_email_provider"),
        CheckConstraint(
            check_in_constraint("match_status", INBOUND_EMAIL_MATCH_STATUSES),
            name="ck_inbound_email_match_status",
        ),
        CheckConstraint(
            check_in_constraint("match_reason", INBOUND_EMAIL_MATCH_REASONS),
            name="ck_inbound_email_match_reason",
        ),
        CheckConstraint(
            check_in_constraint("review_status", INBOUND_EMAIL_REVIEW_STATUSES),
            name="ck_inbound_email_review_status",
        ),
        Index("ix_inbound_email_messages_email_account_id", "email_account_id"),
        Index("ix_inbound_email_messages_order_id", "order_id"),
        Index("ix_inbound_email_messages_match_status", "match_status"),
        Index("ix_inbound_email_messages_provider_thread_id", "provider_thread_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_account_id: Mapped[int] = mapped_column(ForeignKey("email_accounts.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="gmail")
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_thread_id: Mapped[str | None] = mapped_column(String(255))
    gmail_history_id: Mapped[str | None] = mapped_column(String(255))
    from_email: Mapped[str | None] = mapped_column(String(255))
    to_email: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(255))
    snippet: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_headers_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    match_status: Mapped[str] = mapped_column(String(50), nullable=False, default="unlinked")
    match_reason: Mapped[str] = mapped_column(String(50), nullable=False, default="no_match")
    review_status: Mapped[str] = mapped_column(String(50), nullable=False, default="unreviewed")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer)

    email_account: Mapped[EmailAccount] = relationship(back_populates="inbound_messages")
    order: Mapped[ClaimOrder | None] = relationship(back_populates="inbound_email_messages")
    response_reviews: Mapped[list["ClaimResponseReview"]] = relationship(back_populates="inbound_message")
    customer_refund_reviews: Mapped[list["CustomerRefundDisputeReview"]] = relationship(back_populates="inbound_message")
    response_analysis: Mapped["GmailResponseAnalysis | None"] = relationship(
        back_populates="inbound_message",
        uselist=False,
    )


class GmailResponseAnalysis(TimestampMixin, Base):
    __tablename__ = "gmail_response_analyses"
    __table_args__ = (
        UniqueConstraint("inbound_message_id", name="uq_gmail_response_analyses_inbound_message"),
        CheckConstraint(
            check_in_constraint("status", GMAIL_RESPONSE_ANALYSIS_STATUSES),
            name="ck_gmail_response_analyses_status",
        ),
        CheckConstraint(
            check_in_constraint("recommended_review_type", CLAIM_RESPONSE_REVIEW_TYPES),
            name="ck_gmail_response_analyses_review_type",
        ),
        Index("ix_gmail_response_analyses_inbound_message_id", "inbound_message_id"),
        Index("ix_gmail_response_analyses_order_id", "order_id"),
        Index("ix_gmail_response_analyses_status", "status"),
        Index("ix_gmail_response_analyses_recommended_review_type", "recommended_review_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inbound_message_id: Mapped[int] = mapped_column(ForeignKey("inbound_email_messages.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    response_review_id: Mapped[int | None] = mapped_column(ForeignKey("claim_response_reviews.id"))
    analyzed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    applied_by_user_id: Mapped[int | None] = mapped_column(Integer)
    recommended_review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="analyzed")
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    reason: Mapped[str | None] = mapped_column(String(100))
    detected_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_payment_date: Mapped[date | None] = mapped_column(Date)
    evidence_requested: Mapped[bool | None] = mapped_column(Boolean)
    matched_keywords_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    inbound_message: Mapped[InboundEmailMessage] = relationship(back_populates="response_analysis")
    order: Mapped[ClaimOrder | None] = relationship()
    response_review: Mapped["ClaimResponseReview | None"] = relationship()


class ClaimResponseReview(TimestampMixin, Base):
    __tablename__ = "claim_response_reviews"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("review_type", CLAIM_RESPONSE_REVIEW_TYPES),
            name="ck_claim_response_reviews_type",
        ),
        Index("ix_claim_response_reviews_order_id", "order_id"),
        Index("ix_claim_response_reviews_inbound_message_id", "inbound_message_id"),
        Index("ix_claim_response_reviews_reviewed_by_user_id", "reviewed_by_user_id"),
        Index("ix_claim_response_reviews_review_type", "review_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    inbound_message_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_email_messages.id"))
    reviewed_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_order_status: Mapped[str] = mapped_column(String(50), nullable=False)
    new_order_status: Mapped[str] = mapped_column(String(50), nullable=False)
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_payment_date: Mapped[date | None] = mapped_column(Date)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    evidence_requested: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)

    order: Mapped[ClaimOrder] = relationship(back_populates="response_reviews")
    inbound_message: Mapped[InboundEmailMessage | None] = relationship(back_populates="response_reviews")


class FollowUpTask(TimestampMixin, Base):
    __tablename__ = "followup_tasks"
    __table_args__ = (
        UniqueConstraint("order_id", "task_type", name="uq_followup_tasks_order_task_type"),
        CheckConstraint(check_in_constraint("task_type", FOLLOWUP_TASK_TYPES), name="ck_followup_tasks_type"),
        CheckConstraint(check_in_constraint("status", FOLLOWUP_TASK_STATUSES), name="ck_followup_tasks_status"),
        Index("ix_followup_tasks_order_id", "order_id"),
        Index("ix_followup_tasks_status", "status"),
        Index("ix_followup_tasks_task_type", "task_type"),
        Index("ix_followup_tasks_due_at", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_email_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id"))
    generated_provider_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_provider_drafts.id"))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    completed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    skipped_by_user_id: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_reason: Mapped[str | None] = mapped_column(Text)

    order: Mapped[ClaimOrder] = relationship(back_populates="followup_tasks")
    generated_email_draft: Mapped[EmailDraft | None] = relationship(foreign_keys=[generated_email_draft_id])
    generated_provider_draft: Mapped["EmailProviderDraft | None"] = relationship(
        foreign_keys=[generated_provider_draft_id]
    )


class EmailProviderDraft(TimestampMixin, Base):
    __tablename__ = "email_provider_drafts"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("provider", EMAIL_PROVIDER_DRAFT_PROVIDERS),
            name="ck_email_provider_drafts_provider",
        ),
        CheckConstraint(
            check_in_constraint("status", EMAIL_PROVIDER_DRAFT_STATUSES),
            name="ck_email_provider_drafts_status",
        ),
        Index("ix_email_provider_drafts_email_draft_id", "email_draft_id"),
        Index("ix_email_provider_drafts_email_account_id", "email_account_id"),
        Index("ix_email_provider_drafts_created_by_user_id", "created_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id"), nullable=False)
    email_account_id: Mapped[int | None] = mapped_column(ForeignKey("email_accounts.id"))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_draft_id: Mapped[str | None] = mapped_column(String(255))
    provider_thread_id: Mapped[str | None] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_by_user_id: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)

    email_draft: Mapped[EmailDraft] = relationship(back_populates="provider_drafts")
    email_account: Mapped[EmailAccount | None] = relationship()


class AutopilotRun(Base):
    __tablename__ = "autopilot_runs"
    __table_args__ = (
        CheckConstraint(check_in_constraint("status", AUTOPILOT_RUN_STATUSES), name="ck_autopilot_runs_status"),
        CheckConstraint(check_in_constraint("mode", AUTOPILOT_MODES), name="ck_autopilot_runs_mode"),
        Index("ix_autopilot_runs_status", "status"),
        Index("ix_autopilot_runs_mode", "mode"),
        Index("ix_autopilot_runs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_by_user_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    actions: Mapped[list["AutopilotAction"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class AutopilotAction(TimestampMixin, Base):
    __tablename__ = "autopilot_actions"
    __table_args__ = (
        CheckConstraint(check_in_constraint("case_type", AUTOPILOT_CASE_TYPES), name="ck_autopilot_actions_case_type"),
        CheckConstraint(check_in_constraint("action_type", AUTOPILOT_ACTION_TYPES), name="ck_autopilot_actions_action_type"),
        CheckConstraint(check_in_constraint("status", AUTOPILOT_ACTION_STATUSES), name="ck_autopilot_actions_status"),
        Index("ix_autopilot_actions_run_id", "run_id"),
        Index("ix_autopilot_actions_restaurant_id", "restaurant_id"),
        Index("ix_autopilot_actions_case", "case_type", "case_id"),
        Index("ix_autopilot_actions_status", "status"),
        Index("ix_autopilot_actions_sent_at", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("autopilot_runs.id"), nullable=False)
    case_type: Mapped[str] = mapped_column(String(50), nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="candidate")
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    email_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id"))
    provider_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_provider_drafts.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skipped_reason: Mapped[str | None] = mapped_column(Text)

    run: Mapped[AutopilotRun] = relationship(back_populates="actions")
    restaurant: Mapped[Restaurant] = relationship(back_populates="autopilot_actions")
    email_draft: Mapped[EmailDraft | None] = relationship(foreign_keys=[email_draft_id])
    provider_draft: Mapped[EmailProviderDraft | None] = relationship(foreign_keys=[provider_draft_id])


class SmartImportPreviewBatch(TimestampMixin, Base):
    __tablename__ = "smart_import_preview_batches"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("status", SMART_IMPORT_PREVIEW_STATUSES),
            name="ck_smart_import_preview_batches_status",
        ),
        Index("ix_smart_import_preview_batches_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_smart_import_preview_batches_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="previewed")
    files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list["SmartImportPreviewFile"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class SmartImportPreviewFile(TimestampMixin, Base):
    __tablename__ = "smart_import_preview_files"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("detected_category", SMART_IMPORT_FILE_CATEGORIES),
            name="ck_smart_import_preview_files_category",
        ),
        CheckConstraint(
            check_in_constraint("recommended_action", SMART_IMPORT_RECOMMENDED_ACTIONS),
            name="ck_smart_import_preview_files_recommended_action",
        ),
        CheckConstraint(
            check_in_constraint("status", SMART_IMPORT_FILE_STATUSES),
            name="ck_smart_import_preview_files_status",
        ),
        Index("ix_smart_import_preview_files_batch_id", "batch_id"),
        Index("ix_smart_import_preview_files_detected_category", "detected_category"),
        Index("ix_smart_import_preview_files_recommended_action", "recommended_action"),
        Index("ix_smart_import_preview_files_status", "status"),
        Index("ix_smart_import_preview_files_checksum_sha256", "checksum_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("smart_import_preview_batches.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    temp_storage_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    detected_category: Mapped[str] = mapped_column(String(50), nullable=False)
    detected_report_type: Mapped[str | None] = mapped_column(String(50))
    detected_evidence_type: Mapped[str | None] = mapped_column(String(50))
    detected_restaurant_name: Mapped[str | None] = mapped_column(String(255))
    detected_date_from: Mapped[date | None] = mapped_column(Date)
    detected_date_to: Mapped[date | None] = mapped_column(Date)
    header_row_number: Mapped[int | None] = mapped_column(Integer)
    skipped_preamble_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    recommended_action: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="previewed")
    destination_type: Mapped[str | None] = mapped_column(String(50))
    destination_id: Mapped[int | None] = mapped_column(Integer)
    destination_url: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    detected_columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    batch: Mapped[SmartImportPreviewBatch] = relationship(back_populates="files")


class UberIntegrationAccount(TimestampMixin, Base):
    __tablename__ = "uber_integration_accounts"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("provider", UBER_INTEGRATION_PROVIDERS),
            name="ck_uber_integration_accounts_provider",
        ),
        CheckConstraint(check_in_constraint("status", UBER_INTEGRATION_STATUSES), name="ck_uber_integration_accounts_status"),
        Index("ix_uber_integration_accounts_provider", "provider"),
        Index("ix_uber_integration_accounts_created_by_user_id", "created_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="uber_eats")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_configured")
    client_id_encrypted: Mapped[str | None] = mapped_column(Text)
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UberStoreMapping(TimestampMixin, Base):
    __tablename__ = "uber_store_mappings"
    __table_args__ = (
        UniqueConstraint("uber_store_id", name="uq_uber_store_mappings_uber_store_id"),
        Index("ix_uber_store_mappings_restaurant_id", "restaurant_id"),
        Index("ix_uber_store_mappings_active", "active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    uber_store_name: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant_store_id: Mapped[str | None] = mapped_column(String(255))
    external_reference_id: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="uber_store_mappings")


class UberOrderSnapshot(TimestampMixin, Base):
    __tablename__ = "uber_order_snapshots"
    __table_args__ = (
        UniqueConstraint("uber_store_id", "uber_order_id", name="uq_uber_order_snapshots_store_order"),
        CheckConstraint(check_in_constraint("imported_from", UBER_SNAPSHOT_SOURCES), name="ck_uber_order_snapshots_source"),
        Index("ix_uber_order_snapshots_restaurant_id", "restaurant_id"),
        Index("ix_uber_order_snapshots_uber_order_id", "uber_order_id"),
        Index("ix_uber_order_snapshots_current_state", "current_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    uber_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_id: Mapped[str | None] = mapped_column(String(255))
    current_state: Mapped[str] = mapped_column(String(100), nullable=False)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    imported_from: Mapped[str] = mapped_column(String(50), nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="uber_order_snapshots")


class UberFinancialTransaction(Base):
    __tablename__ = "uber_financial_transactions"
    __table_args__ = (
        CheckConstraint(check_in_constraint("imported_from", UBER_SNAPSHOT_SOURCES), name="ck_uber_financial_transactions_source"),
        Index("ix_uber_financial_transactions_restaurant_id", "restaurant_id"),
        Index("ix_uber_financial_transactions_uber_order_id", "uber_order_id"),
        Index("ix_uber_financial_transactions_transaction_date", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_store_id: Mapped[str] = mapped_column(String(255), nullable=False)
    uber_order_id: Mapped[str | None] = mapped_column(String(255))
    transaction_type: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    payout_reference: Mapped[str | None] = mapped_column(String(255))
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    imported_from: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="uber_financial_transactions")
    customer_refund_disputes: Mapped[list["UberCustomerRefundDispute"]] = relationship(back_populates="financial_transaction")


class UberCustomerRefundDispute(TimestampMixin, Base):
    __tablename__ = "uber_customer_refund_disputes"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("dispute_type", CUSTOMER_REFUND_DISPUTE_TYPES),
            name="ck_customer_refund_disputes_type",
        ),
        CheckConstraint(
            check_in_constraint("reason", CUSTOMER_REFUND_DISPUTE_REASONS),
            name="ck_customer_refund_disputes_reason",
        ),
        CheckConstraint(
            check_in_constraint("status", CUSTOMER_REFUND_DISPUTE_STATUSES),
            name="ck_customer_refund_disputes_status",
        ),
        CheckConstraint(
            check_in_constraint("evidence_status", CUSTOMER_REFUND_EVIDENCE_STATUSES),
            name="ck_customer_refund_disputes_evidence_status",
        ),
        Index("ix_customer_refund_disputes_restaurant_id", "restaurant_id"),
        Index("ix_customer_refund_disputes_status", "status"),
        Index("ix_customer_refund_disputes_evidence_status", "evidence_status"),
        Index("ix_customer_refund_disputes_dispute_type", "dispute_type"),
        Index("ix_customer_refund_disputes_financial_transaction_id", "financial_transaction_id"),
        Index("ix_customer_refund_disputes_claim_order_id", "claim_order_id"),
        Index("ix_customer_refund_disputes_deducted_at", "deducted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_store_id: Mapped[str | None] = mapped_column(String(255))
    uber_order_id: Mapped[str | None] = mapped_column(String(255))
    display_id: Mapped[str | None] = mapped_column(String(255))
    claim_order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    financial_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("uber_financial_transactions.id"), unique=True)
    customer_refund_reference: Mapped[str | None] = mapped_column(String(255))
    dispute_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="detected")
    customer_refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    deducted_at: Mapped[date | None] = mapped_column(Date)
    order_date: Mapped[date | None] = mapped_column(Date)
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence_status: Mapped[str] = mapped_column(String(50), nullable=False, default="missing")
    dispute_email_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id"))
    provider_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_provider_drafts.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    raw_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ignored_by_user_id: Mapped[int | None] = mapped_column(Integer)
    ignore_reason: Mapped[str | None] = mapped_column(Text)
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_payment_date: Mapped[date | None] = mapped_column(Date)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer)

    restaurant: Mapped[Restaurant] = relationship(back_populates="customer_refund_disputes")
    claim_order: Mapped[ClaimOrder | None] = relationship(back_populates="customer_refund_disputes")
    financial_transaction: Mapped[UberFinancialTransaction | None] = relationship(back_populates="customer_refund_disputes")
    dispute_email_draft: Mapped[EmailDraft | None] = relationship(foreign_keys=[dispute_email_draft_id])
    provider_draft: Mapped[EmailProviderDraft | None] = relationship(foreign_keys=[provider_draft_id])
    evidence_requirements: Mapped[list["CustomerRefundEvidenceRequirement"]] = relationship(
        back_populates="dispute",
        cascade="all, delete-orphan",
    )
    evidence_request_tasks: Mapped[list["EvidenceRequestTask"]] = relationship(back_populates="customer_refund_dispute")
    reviews: Mapped[list["CustomerRefundDisputeReview"]] = relationship(back_populates="dispute")


class CustomerRefundEvidenceRequirement(TimestampMixin, Base):
    __tablename__ = "customer_refund_evidence_requirements"
    __table_args__ = (
        UniqueConstraint("dispute_id", "required_evidence_type", name="uq_customer_refund_requirement_type"),
        CheckConstraint(
            check_in_constraint("required_evidence_type", EVIDENCE_TYPES),
            name="ck_customer_refund_requirements_evidence_type",
        ),
        CheckConstraint(
            check_in_constraint("status", CUSTOMER_REFUND_REQUIREMENT_STATUSES),
            name="ck_customer_refund_requirements_status",
        ),
        Index("ix_customer_refund_requirements_dispute_id", "dispute_id"),
        Index("ix_customer_refund_requirements_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("uber_customer_refund_disputes.id"), nullable=False)
    required_evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    evidence_file_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_files.id"))

    dispute: Mapped[UberCustomerRefundDispute] = relationship(back_populates="evidence_requirements")
    evidence_file: Mapped[EvidenceFile | None] = relationship()


class CustomerRefundDisputeReview(TimestampMixin, Base):
    __tablename__ = "customer_refund_dispute_reviews"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("review_type", CUSTOMER_REFUND_REVIEW_TYPES),
            name="ck_customer_refund_dispute_reviews_type",
        ),
        Index("ix_customer_refund_dispute_reviews_dispute_id", "dispute_id"),
        Index("ix_customer_refund_dispute_reviews_inbound_message_id", "inbound_message_id"),
        Index("ix_customer_refund_dispute_reviews_reviewed_by_user_id", "reviewed_by_user_id"),
        Index("ix_customer_refund_dispute_reviews_review_type", "review_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dispute_id: Mapped[int] = mapped_column(ForeignKey("uber_customer_refund_disputes.id"), nullable=False)
    inbound_message_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_email_messages.id"))
    reviewed_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_dispute_status: Mapped[str] = mapped_column(String(50), nullable=False)
    new_dispute_status: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_claim_order_status: Mapped[str | None] = mapped_column(String(50))
    new_claim_order_status: Mapped[str | None] = mapped_column(String(50))
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    expected_payment_date: Mapped[date | None] = mapped_column(Date)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    evidence_requested: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)

    dispute: Mapped[UberCustomerRefundDispute] = relationship(back_populates="reviews")
    inbound_message: Mapped[InboundEmailMessage | None] = relationship(back_populates="customer_refund_reviews")


class UberReconciliationRun(Base):
    __tablename__ = "uber_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("status", UBER_RECONCILIATION_RUN_STATUSES),
            name="ck_uber_reconciliation_runs_status",
        ),
        Index("ix_uber_reconciliation_runs_created_by_user_id", "created_by_user_id"),
        Index("ix_uber_reconciliation_runs_restaurant_id", "restaurant_id"),
        Index("ix_uber_reconciliation_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"))
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    total_orders_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canceled_orders_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compensated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_compensated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partially_compensated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    already_claimed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_claimable_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    total_missing_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    restaurant: Mapped[Restaurant | None] = relationship(back_populates="uber_reconciliation_runs")
    results: Mapped[list["UberReconciliationResult"]] = relationship(back_populates="run")


class UberReconciliationResult(TimestampMixin, Base):
    __tablename__ = "uber_reconciliation_results"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "uber_order_id", name="uq_uber_reconciliation_results_restaurant_order"),
        CheckConstraint(
            check_in_constraint("status", UBER_RECONCILIATION_STATUSES),
            name="ck_uber_reconciliation_results_status",
        ),
        CheckConstraint(
            f"financial_status IS NULL OR {check_in_constraint('financial_status', UBER_RECONCILIATION_FINANCIAL_STATUSES)}",
            name="ck_uber_reconciliation_results_financial_status",
        ),
        Index("ix_uber_reconciliation_results_restaurant_id", "restaurant_id"),
        Index("ix_uber_reconciliation_results_status", "status"),
        Index("ix_uber_reconciliation_results_financial_status", "financial_status"),
        Index("ix_uber_reconciliation_results_claim_order_id", "claim_order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("uber_reconciliation_runs.id"))
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_id: Mapped[str | None] = mapped_column(String(255))
    claim_order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    financial_status: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    missing_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    matched_transaction_ids_json: Mapped[list[int] | None] = mapped_column(JSON)
    matched_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("uber_order_snapshots.id"))

    run: Mapped[UberReconciliationRun | None] = relationship(back_populates="results")
    restaurant: Mapped[Restaurant] = relationship(back_populates="uber_reconciliation_results")
    claim_order: Mapped[ClaimOrder | None] = relationship()
    matched_snapshot: Mapped[UberOrderSnapshot | None] = relationship()
    evidence_request_tasks: Mapped[list["EvidenceRequestTask"]] = relationship(back_populates="reconciliation_result")


class EvidenceRequestTask(TimestampMixin, Base):
    __tablename__ = "evidence_request_tasks"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("task_type", EVIDENCE_REQUEST_TASK_TYPES),
            name="ck_evidence_request_tasks_task_type",
        ),
        CheckConstraint(
            check_in_constraint("required_evidence_type", EVIDENCE_TYPES),
            name="ck_evidence_request_tasks_required_type",
        ),
        CheckConstraint(
            check_in_constraint("status", EVIDENCE_REQUEST_TASK_STATUSES),
            name="ck_evidence_request_tasks_status",
        ),
        CheckConstraint(
            check_in_constraint("priority", EVIDENCE_REQUEST_PRIORITIES),
            name="ck_evidence_request_tasks_priority",
        ),
        Index("ix_evidence_request_tasks_order_id", "order_id"),
        Index("ix_evidence_request_tasks_restaurant_id", "restaurant_id"),
        Index("ix_evidence_request_tasks_status", "status"),
        Index("ix_evidence_request_tasks_priority", "priority"),
        Index("ix_evidence_request_tasks_task_type", "task_type"),
        Index("ix_evidence_request_tasks_required_type", "required_evidence_type"),
        Index("ix_evidence_request_tasks_reconciliation_result_id", "reconciliation_result_id"),
        Index("ix_evidence_request_tasks_customer_refund_dispute_id", "customer_refund_dispute_id"),
        Index("ix_evidence_request_tasks_due_at", "due_at"),
        Index("ix_evidence_request_tasks_assigned_to_user_id", "assigned_to_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    reconciliation_result_id: Mapped[int | None] = mapped_column(ForeignKey("uber_reconciliation_results.id"))
    customer_refund_dispute_id: Mapped[int | None] = mapped_column(ForeignKey("uber_customer_refund_disputes.id"))
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    required_evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to_user_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    completed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    skipped_by_user_id: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skip_reason: Mapped[str | None] = mapped_column(Text)
    last_upload_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_files.id"))

    order: Mapped[ClaimOrder] = relationship(back_populates="evidence_request_tasks")
    restaurant: Mapped[Restaurant] = relationship(back_populates="evidence_request_tasks")
    reconciliation_result: Mapped[UberReconciliationResult | None] = relationship(
        back_populates="evidence_request_tasks"
    )
    customer_refund_dispute: Mapped[UberCustomerRefundDispute | None] = relationship(back_populates="evidence_request_tasks")
    last_upload_evidence: Mapped[EvidenceFile | None] = relationship(foreign_keys=[last_upload_evidence_id])
    upload_links: Mapped[list["EvidenceUploadLink"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )


class EvidenceUploadLink(TimestampMixin, Base):
    __tablename__ = "evidence_upload_links"
    __table_args__ = (
        Index("ix_evidence_upload_links_task_id", "task_id"),
        Index("ix_evidence_upload_links_token_hash", "token_hash", unique=True),
        Index("ix_evidence_upload_links_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("evidence_request_tasks.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[EvidenceRequestTask] = relationship(back_populates="upload_links")


class EvidenceImportBatch(TimestampMixin, Base):
    __tablename__ = "evidence_import_batches"
    __table_args__ = (
        CheckConstraint(check_in_constraint("source_type", EVIDENCE_IMPORT_SOURCE_TYPES), name="ck_evidence_import_batches_source_type"),
        CheckConstraint(check_in_constraint("status", EVIDENCE_IMPORT_BATCH_STATUSES), name="ck_evidence_import_batches_status"),
        Index("ix_evidence_import_batches_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_evidence_import_batches_restaurant_id", "restaurant_id"),
        Index("ix_evidence_import_batches_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stored_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    restaurant: Mapped[Restaurant | None] = relationship(back_populates="evidence_import_batches")
    files: Mapped[list["EvidenceImportedFile"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class EvidenceImportedFile(TimestampMixin, Base):
    __tablename__ = "evidence_imported_files"
    __table_args__ = (
        CheckConstraint(check_in_constraint("status", EVIDENCE_IMPORTED_FILE_STATUSES), name="ck_evidence_imported_files_status"),
        Index("ix_evidence_imported_files_batch_id", "batch_id"),
        Index("ix_evidence_imported_files_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_evidence_imported_files_status", "status"),
        Index("ix_evidence_imported_files_checksum_sha256", "checksum_sha256"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("evidence_import_batches.id"), nullable=False)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(50), nullable=False, default="local")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="stored")

    batch: Mapped[EvidenceImportBatch] = relationship(back_populates="files")
    analysis_results: Mapped[list["EvidenceAnalysisResult"]] = relationship(back_populates="imported_file", cascade="all, delete-orphan")
    match_candidates: Mapped[list["EvidenceMatchCandidate"]] = relationship(back_populates="imported_file", cascade="all, delete-orphan")
    attachment_decisions: Mapped[list["EvidenceAttachmentDecision"]] = relationship(back_populates="imported_file", cascade="all, delete-orphan")

    @property
    def preview_url(self) -> str:
        return f"/v1/evidence-imported-files/{self.id}/preview"


class EvidenceAnalysisResult(TimestampMixin, Base):
    __tablename__ = "evidence_analysis_results"
    __table_args__ = (
        CheckConstraint(check_in_constraint("provider", EVIDENCE_ANALYSIS_PROVIDERS), name="ck_evidence_analysis_results_provider"),
        CheckConstraint(check_in_constraint("status", EVIDENCE_ANALYSIS_STATUSES), name="ck_evidence_analysis_results_status"),
        CheckConstraint(check_in_constraint("detected_evidence_type", EVIDENCE_ANALYSIS_TYPES), name="ck_evidence_analysis_results_type"),
        Index("ix_evidence_analysis_results_imported_file_id", "imported_file_id"),
        Index("ix_evidence_analysis_results_status", "status"),
        Index("ix_evidence_analysis_results_detected_type", "detected_evidence_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_file_id: Mapped[int] = mapped_column(ForeignKey("evidence_imported_files.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    detected_evidence_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    detected_restaurant_name: Mapped[str | None] = mapped_column(String(255))
    detected_uber_order_number: Mapped[str | None] = mapped_column(String(255))
    detected_display_id: Mapped[str | None] = mapped_column(String(255))
    detected_order_date: Mapped[date | None] = mapped_column(Date)
    detected_order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    detected_currency: Mapped[str | None] = mapped_column(String(3))
    detected_keywords_json: Mapped[list[str] | None] = mapped_column(JSON)
    classification_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    extraction_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    matching_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    raw_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    imported_file: Mapped[EvidenceImportedFile] = relationship(back_populates="analysis_results")
    match_candidates: Mapped[list["EvidenceMatchCandidate"]] = relationship(back_populates="analysis_result", cascade="all, delete-orphan")


class EvidenceMatchCandidate(TimestampMixin, Base):
    __tablename__ = "evidence_match_candidates"
    __table_args__ = (
        CheckConstraint(check_in_constraint("candidate_type", EVIDENCE_MATCH_CANDIDATE_TYPES), name="ck_evidence_match_candidates_type"),
        CheckConstraint(check_in_constraint("status", EVIDENCE_MATCH_STATUSES), name="ck_evidence_match_candidates_status"),
        CheckConstraint(check_in_constraint("match_reason", EVIDENCE_MATCH_REASONS), name="ck_evidence_match_candidates_reason"),
        Index("ix_evidence_match_candidates_imported_file_id", "imported_file_id"),
        Index("ix_evidence_match_candidates_analysis_result_id", "analysis_result_id"),
        Index("ix_evidence_match_candidates_candidate", "candidate_type", "candidate_id"),
        Index("ix_evidence_match_candidates_restaurant_id", "restaurant_id"),
        Index("ix_evidence_match_candidates_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_file_id: Mapped[int] = mapped_column(ForeignKey("evidence_imported_files.id"), nullable=False)
    analysis_result_id: Mapped[int] = mapped_column(ForeignKey("evidence_analysis_results.id"), nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int | None] = mapped_column(ForeignKey("restaurants.id"))
    match_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    match_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="proposed")
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    imported_file: Mapped[EvidenceImportedFile] = relationship(back_populates="match_candidates")
    analysis_result: Mapped[EvidenceAnalysisResult] = relationship(back_populates="match_candidates")
    restaurant: Mapped[Restaurant | None] = relationship()


class EvidenceAttachmentDecision(Base):
    __tablename__ = "evidence_attachment_decisions"
    __table_args__ = (
        CheckConstraint(check_in_constraint("candidate_type", EVIDENCE_MATCH_CANDIDATE_TYPES), name="ck_evidence_attachment_decisions_type"),
        CheckConstraint(check_in_constraint("decision", EVIDENCE_ATTACHMENT_DECISIONS), name="ck_evidence_attachment_decisions_decision"),
        Index("ix_evidence_attachment_decisions_imported_file_id", "imported_file_id"),
        Index("ix_evidence_attachment_decisions_evidence_file_id", "evidence_file_id"),
        Index("ix_evidence_attachment_decisions_candidate", "candidate_type", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_file_id: Mapped[int] = mapped_column(ForeignKey("evidence_imported_files.id"), nullable=False)
    evidence_file_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_files.id"))
    candidate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    decided_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    imported_file: Mapped[EvidenceImportedFile] = relationship(back_populates="attachment_decisions")
    evidence_file: Mapped[EvidenceFile | None] = relationship(back_populates="attachment_decisions")


class AppealWorkflow(TimestampMixin, Base):
    __tablename__ = "appeal_workflows"
    __table_args__ = (
        UniqueConstraint("case_type", "case_id", name="uq_appeal_workflows_case"),
        CheckConstraint(check_in_constraint("case_type", APPEAL_CASE_TYPES), name="ck_appeal_workflows_case_type"),
        CheckConstraint(check_in_constraint("status", APPEAL_WORKFLOW_STATUSES), name="ck_appeal_workflows_status"),
        CheckConstraint(check_in_constraint("next_action_type", APPEAL_NEXT_ACTION_TYPES), name="ck_appeal_workflows_next_action_type"),
        Index("ix_appeal_workflows_restaurant_id", "restaurant_id"),
        Index("ix_appeal_workflows_status", "status"),
        Index("ix_appeal_workflows_next_action_type", "next_action_type"),
        Index("ix_appeal_workflows_claim_order_id", "claim_order_id"),
        Index("ix_appeal_workflows_customer_refund_dispute_id", "customer_refund_dispute_id"),
        Index("ix_appeal_workflows_reconciliation_result_id", "reconciliation_result_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_type: Mapped[str] = mapped_column(String(50), nullable=False)
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    claim_order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    customer_refund_dispute_id: Mapped[int | None] = mapped_column(ForeignKey("uber_customer_refund_disputes.id"))
    reconciliation_result_id: Mapped[int | None] = mapped_column(ForeignKey("uber_reconciliation_results.id"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    current_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refusal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    appeal_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_refusal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_appeal_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_type: Mapped[str | None] = mapped_column(String(50))
    opened_by_user_id: Mapped[int | None] = mapped_column(Integer)
    manually_closed_by_user_id: Mapped[int | None] = mapped_column(Integer)
    manually_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_close_reason: Mapped[str | None] = mapped_column(Text)

    restaurant: Mapped[Restaurant] = relationship(back_populates="appeal_workflows")
    claim_order: Mapped[ClaimOrder | None] = relationship(back_populates="appeal_workflows")
    customer_refund_dispute: Mapped[UberCustomerRefundDispute | None] = relationship()
    reconciliation_result: Mapped[UberReconciliationResult | None] = relationship()
    attempts: Mapped[list["AppealAttempt"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    refusal_analyses: Mapped[list["RefusalAnalysis"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class AppealAttempt(Base):
    __tablename__ = "appeal_attempts"
    __table_args__ = (
        CheckConstraint(check_in_constraint("appeal_type", APPEAL_TYPES), name="ck_appeal_attempts_type"),
        CheckConstraint(check_in_constraint("status", APPEAL_ATTEMPT_STATUSES), name="ck_appeal_attempts_status"),
        UniqueConstraint("workflow_id", "attempt_number", name="uq_appeal_attempts_number"),
        Index("ix_appeal_attempts_workflow_id", "workflow_id"),
        Index("ix_appeal_attempts_status", "status"),
        Index("ix_appeal_attempts_email_draft_id", "email_draft_id"),
        Index("ix_appeal_attempts_provider_draft_id", "provider_draft_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("appeal_workflows.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    appeal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned")
    based_on_refusal_message_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_email_messages.id"))
    email_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_drafts.id"))
    provider_draft_id: Mapped[int | None] = mapped_column(ForeignKey("email_provider_drafts.id"))
    sent_email_thread_id: Mapped[int | None] = mapped_column(ForeignKey("email_threads.id"))
    argument_summary: Mapped[str | None] = mapped_column(Text)
    new_evidence_summary: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)
    sent_by_user_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[AppealWorkflow] = relationship(back_populates="attempts")
    email_draft: Mapped[EmailDraft | None] = relationship(foreign_keys=[email_draft_id])
    provider_draft: Mapped[EmailProviderDraft | None] = relationship(foreign_keys=[provider_draft_id])
    sent_email_thread: Mapped[EmailThread | None] = relationship(foreign_keys=[sent_email_thread_id])


class RefusalAnalysis(Base):
    __tablename__ = "refusal_analyses"
    __table_args__ = (
        CheckConstraint(check_in_constraint("refusal_source", REFUSAL_SOURCES), name="ck_refusal_analyses_source"),
        CheckConstraint(check_in_constraint("recommended_next_action", REFUSAL_NEXT_ACTIONS), name="ck_refusal_analyses_next_action"),
        Index("ix_refusal_analyses_workflow_id", "workflow_id"),
        Index("ix_refusal_analyses_inbound_message_id", "inbound_message_id"),
        Index("ix_refusal_analyses_review_id", "review_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("appeal_workflows.id"), nullable=False)
    inbound_message_id: Mapped[int | None] = mapped_column(ForeignKey("inbound_email_messages.id"))
    review_id: Mapped[int | None] = mapped_column(Integer)
    refusal_source: Mapped[str] = mapped_column(String(50), nullable=False)
    refusal_reason: Mapped[str] = mapped_column(String(255), nullable=False)
    refusal_text_excerpt: Mapped[str | None] = mapped_column(Text)
    recommended_next_action: Mapped[str] = mapped_column(String(50), nullable=False)
    required_evidence_types_json: Mapped[list[str] | None] = mapped_column(JSON)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    workflow: Mapped[AppealWorkflow] = relationship(back_populates="refusal_analyses")


class UberReportingImportBatch(TimestampMixin, Base):
    __tablename__ = "uber_reporting_import_batches"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("report_type", UBER_REPORTING_IMPORT_REPORT_TYPES),
            name="ck_uber_reporting_import_batches_report_type",
        ),
        CheckConstraint(
            check_in_constraint("status", UBER_REPORTING_IMPORT_BATCH_STATUSES),
            name="ck_uber_reporting_import_batches_status",
        ),
        Index("ix_uber_reporting_import_batches_uploaded_by_user_id", "uploaded_by_user_id"),
        Index("ix_uber_reporting_import_batches_status", "status"),
        Index("ix_uber_reporting_import_batches_report_type", "report_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="uploaded")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_snapshots_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_transactions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows: Mapped[list["UberReportingImportRow"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class UberReportingImportRow(Base):
    __tablename__ = "uber_reporting_import_rows"
    __table_args__ = (
        CheckConstraint(
            check_in_constraint("status", UBER_REPORTING_IMPORT_ROW_STATUSES),
            name="ck_uber_reporting_import_rows_status",
        ),
        Index("ix_uber_reporting_import_rows_batch_id", "batch_id"),
        Index("ix_uber_reporting_import_rows_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("uber_reporting_import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("uber_order_snapshots.id"))
    created_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("uber_financial_transactions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    batch: Mapped[UberReportingImportBatch] = relationship(back_populates="rows")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

