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
    "other",
)

EMAIL_DRAFT_TYPES = (
    "initial_claim",
    "followup_1",
    "followup_2",
    "escalation",
    "proof_reply",
)

EMAIL_DRAFT_STATUSES = ("created", "draft", "ready", "archived")
EMAIL_DIRECTIONS = ("inbound", "outbound")
EMAIL_PROVIDERS = ("internal", "gmail", "microsoft_graph")
USER_ROLES = ("owner", "manager", "staff")
IMPORT_BATCH_STATUSES = ("uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled")
IMPORT_ROW_STATUSES = ("valid", "invalid", "duplicate", "unauthorized", "created", "skipped")
EMAIL_ACCOUNT_PROVIDERS = ("gmail",)
EMAIL_PROVIDER_DRAFT_PROVIDERS = ("gmail",)
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
FOLLOWUP_TASK_TYPES = ("followup_1", "followup_2", "escalation", "manual_review", "payment_verification")
FOLLOWUP_TASK_STATUSES = (
    "pending",
    "draft_created",
    "provider_draft_created",
    "completed",
    "skipped",
    "cancelled",
)
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

    orders: Mapped[list["ClaimOrder"]] = relationship(back_populates="restaurant")
    user_access: Mapped[list[UserRestaurantAccess]] = relationship(back_populates="restaurant")
    uber_store_mappings: Mapped[list["UberStoreMapping"]] = relationship(back_populates="restaurant")
    uber_order_snapshots: Mapped[list["UberOrderSnapshot"]] = relationship(back_populates="restaurant")
    uber_financial_transactions: Mapped[list["UberFinancialTransaction"]] = relationship(back_populates="restaurant")
    uber_reconciliation_results: Mapped[list["UberReconciliationResult"]] = relationship(back_populates="restaurant")


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
        Index("ix_email_provider_drafts_created_by_user_id", "created_by_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id"), nullable=False)
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


class UberReconciliationResult(TimestampMixin, Base):
    __tablename__ = "uber_reconciliation_results"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "uber_order_id", name="uq_uber_reconciliation_results_restaurant_order"),
        CheckConstraint(
            check_in_constraint("status", UBER_RECONCILIATION_STATUSES),
            name="ck_uber_reconciliation_results_status",
        ),
        Index("ix_uber_reconciliation_results_restaurant_id", "restaurant_id"),
        Index("ix_uber_reconciliation_results_status", "status"),
        Index("ix_uber_reconciliation_results_claim_order_id", "claim_order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    uber_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_order_id: Mapped[int | None] = mapped_column(ForeignKey("claim_orders.id"))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    order_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    refunded_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    missing_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    restaurant: Mapped[Restaurant] = relationship(back_populates="uber_reconciliation_results")
    claim_order: Mapped[ClaimOrder | None] = relationship()


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

