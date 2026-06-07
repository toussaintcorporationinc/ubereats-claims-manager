from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

EMAIL_DRAFT_STATUSES = ("draft", "ready", "archived")
EMAIL_DIRECTIONS = ("inbound", "outbound")
EMAIL_PROVIDERS = ("internal", "gmail", "microsoft_graph")


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


class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    __table_args__ = (
        CheckConstraint(check_in_constraint("evidence_type", EVIDENCE_TYPES), name="ck_evidence_files_type"),
        Index("ix_evidence_files_order_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("claim_orders.id"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    order: Mapped[ClaimOrder] = relationship(back_populates="evidence_files")


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

