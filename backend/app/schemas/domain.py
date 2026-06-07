from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal

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
EmailDraftStatus = Literal["created", "draft", "ready", "archived"]
UserRole = Literal["owner", "manager", "staff"]
ImportBatchStatus = Literal["uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled"]
ImportRowStatus = Literal["valid", "invalid", "duplicate", "unauthorized", "created", "skipped"]


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str | None
    role: UserRole
    active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=8)
    full_name: str | None = None
    role: UserRole
    active: bool = True


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=8)
    full_name: str | None = None
    role: UserRole | None = None
    active: bool | None = None


class UserRestaurantAccessCreate(BaseModel):
    restaurant_id: int


class UserRestaurantAccessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    restaurant_id: int
    created_at: datetime


class RegisterRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=8)
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


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
    storage_backend: str
    mime_type: str | None
    file_size: int | None
    checksum_sha256: str | None
    uploaded_by_user_id: int | None
    uploaded_at: datetime
    created_at: datetime
    deleted_at: datetime | None
    download_url: str | None


class EmailDraftCreate(BaseModel):
    draft_type: EmailDraftType


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


class EmailDraftSummaryRead(BaseModel):
    id: int
    order_id: int
    draft_type: EmailDraftType
    subject: str
    status: EmailDraftStatus
    created_at: datetime
    restaurant_name: str | None
    uber_order_number: str | None


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


class ImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    row_number: int
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any] | None
    status: ImportRowStatus
    errors: list[str]
    warnings: list[str]
    created_order_id: int | None
    created_at: datetime


class ImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    uploaded_by_user_id: int
    original_filename: str
    file_type: str
    status: ImportBatchStatus
    total_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    unauthorized_rows: int
    created_orders_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class ImportPreviewResponse(ImportBatchRead):
    rows_preview: list[ImportRowRead]


class ImportRowsResponse(BaseModel):
    rows: list[ImportRowRead]
    limit: int
    offset: int


class ImportConfirmResponse(BaseModel):
    batch_id: int
    status: ImportBatchStatus
    created_orders_count: int
    skipped_rows: int
    errors: list[str]

