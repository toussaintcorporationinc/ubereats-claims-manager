from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimOrderStatus = Literal[
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
]

EvidenceType = Literal[
    "receipt",
    "cancellation_proof",
    "preparation_proof",
    "waste_photo",
    "uber_screenshot",
    "other",
]

EmailDraftType = Literal["initial_claim", "followup_1", "followup_2", "escalation", "proof_reply"]
EmailDraftStatus = Literal["draft", "ready", "archived"]


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1)
    legal_name: str | None = None
    address: str | None = None
    sender_email: str = Field(min_length=1)
    uber_merchant_id: str | None = None
    active: bool = True


class RestaurantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    legal_name: str | None = None
    address: str | None = None
    sender_email: str | None = Field(default=None, min_length=1)
    uber_merchant_id: str | None = None
    active: bool | None = None


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    address: str | None
    sender_email: str
    uber_merchant_id: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


class ClaimOrderCreate(BaseModel):
    restaurant_id: int
    internal_reference: str | None = None
    uber_order_number: str = Field(min_length=1)
    customer_name: str | None = None
    order_date: date | None = None
    order_time: time | None = None
    cancellation_time: time | None = None
    order_amount: Decimal
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    accepted_by_restaurant: bool | None = None
    prepared_before_cancellation: bool | None = None
    loss_type: str | None = None
    status: ClaimOrderStatus = "draft"
    retry_count: int = Field(default=0, ge=0)
    first_email_sent_at: datetime | None = None
    last_followup_sent_at: datetime | None = None
    next_action_at: datetime | None = None
    result: str | None = None
    recovered_amount: Decimal | None = None
    notes: str | None = None


class ClaimOrderUpdate(BaseModel):
    internal_reference: str | None = None
    customer_name: str | None = None
    order_date: date | None = None
    order_time: time | None = None
    cancellation_time: time | None = None
    order_amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    accepted_by_restaurant: bool | None = None
    prepared_before_cancellation: bool | None = None
    loss_type: str | None = None
    status: ClaimOrderStatus | None = None
    retry_count: int | None = Field(default=None, ge=0)
    first_email_sent_at: datetime | None = None
    last_followup_sent_at: datetime | None = None
    next_action_at: datetime | None = None
    result: str | None = None
    recovered_amount: Decimal | None = None
    notes: str | None = None


class ClaimOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    internal_reference: str | None
    uber_order_number: str
    customer_name: str | None
    order_date: date | None
    order_time: time | None
    cancellation_time: time | None
    order_amount: Decimal | None
    currency: str
    accepted_by_restaurant: bool | None
    prepared_before_cancellation: bool | None
    loss_type: str | None
    status: ClaimOrderStatus
    retry_count: int
    first_email_sent_at: datetime | None
    last_followup_sent_at: datetime | None
    next_action_at: datetime | None
    result: str | None
    recovered_amount: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceFileCreate(BaseModel):
    evidence_type: EvidenceType
    original_filename: str = Field(min_length=1)
    storage_path: str = Field(min_length=1)
    mime_type: str | None = None
    file_size: int | None = Field(default=None, ge=0)


class EvidenceFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    evidence_type: EvidenceType
    original_filename: str
    storage_path: str
    mime_type: str | None
    file_size: int | None
    uploaded_at: datetime


class EmailDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    draft_type: EmailDraftType
    subject: str
    body: str
    status: EmailDraftStatus
    created_at: datetime
    updated_at: datetime


class DashboardRestaurantSummary(BaseModel):
    restaurant_id: int
    restaurant_name: str
    total_orders: int
    total_claimed_amount: Decimal
    total_recovered_amount: Decimal


class DashboardSummary(BaseModel):
    total_orders: int
    total_claimed_amount: Decimal
    total_recovered_amount: Decimal
    total_pending_amount: Decimal
    total_refused_amount: Decimal
    orders_by_status: dict[str, int]
    orders_by_restaurant: list[DashboardRestaurantSummary]


MissingClaimItem = Literal[
    "restaurant",
    "uber_order_number",
    "order_amount",
    "currency",
    "cancellation_proof",
    "preparation_or_waste_proof",
]

ClaimValidationBlockingReason = Literal[
    "missing_restaurant",
    "missing_uber_order_number",
    "missing_order_amount",
    "missing_currency",
    "missing_cancellation_proof",
    "missing_preparation_or_waste_proof",
    "final_status_cannot_be_validated",
    "order_not_found",
]


class ClaimValidationResponse(BaseModel):
    order_id: int
    is_complete: bool
    previous_status: ClaimOrderStatus | None
    new_status: ClaimOrderStatus | None
    missing_items: list[MissingClaimItem]
    blocking_reasons: list[ClaimValidationBlockingReason]

