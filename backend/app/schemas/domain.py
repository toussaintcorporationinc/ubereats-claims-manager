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
]

EvidenceType = Literal[
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
]
EvidenceRequestTaskType = Literal[
    "missing_receipt",
    "missing_cancellation_proof",
    "missing_preparation_proof",
    "missing_waste_photo",
    "missing_uber_screenshot",
    "evidence_review",
]
EvidenceRequestTaskStatus = Literal["pending", "uploaded", "completed", "skipped", "cancelled"]
EvidenceRequestPriority = Literal["low", "normal", "high", "urgent"]

EmailDraftType = Literal[
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
]
EmailDraftStatus = Literal["created", "draft", "ready", "archived"]
UserRole = Literal["owner", "manager", "staff"]
ImportBatchStatus = Literal["uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled"]
ImportRowStatus = Literal["valid", "invalid", "duplicate", "unauthorized", "created", "skipped"]
EmailProviderName = Literal["gmail", "resend"]
EmailProviderDraftStatus = Literal["provider_draft_created", "send_requested", "sent", "failed"]
GmailSyncStatus = Literal["idle", "running", "success", "failed"]
InboundEmailMatchStatus = Literal["linked", "unlinked", "ignored"]
GmailResponseAnalysisStatus = Literal["analyzed", "applied", "manual_review", "ignored", "failed"]
InboundEmailMatchReason = Literal[
    "thread_id_match",
    "order_number_match",
    "subject_match",
    "manual_link",
    "no_match",
    "ignored_sender",
]
InboundEmailReviewStatus = Literal["unreviewed", "reviewed", "ignored"]
ClaimResponseReviewType = Literal[
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "evidence_requested",
    "information_requested",
    "followup_needed",
    "ignored",
    "manual_review",
]
CustomerRefundReviewType = ClaimResponseReviewType
FollowUpTaskType = Literal["followup_1", "followup_2", "escalation", "manual_review", "payment_verification"]
FollowUpTaskStatus = Literal[
    "pending",
    "draft_created",
    "provider_draft_created",
    "completed",
    "skipped",
    "cancelled",
]
UberIntegrationStatus = Literal["not_configured", "pending_approval", "connected", "disconnected", "disabled"]
UberImportedFrom = Literal["api_orders", "api_reporting", "manager_export"]
UberReconciliationStatus = Literal[
    "compensated",
    "not_compensated",
    "partially_compensated",
    "needs_evidence",
    "already_claimed",
    "ignored",
    "manual_review",
]
UberReconciliationFinancialStatus = Literal[
    "compensated",
    "not_compensated",
    "partially_compensated",
    "manual_review",
    "not_cancelled",
]
UberReconciliationRunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
UberReportingReportType = Literal["orders_report", "payments_report", "adjustments_report", "combined_report"]
UberReportingBatchStatus = Literal["uploaded", "parsed", "confirmed", "partially_imported", "failed", "cancelled"]
UberReportingRowStatus = Literal["valid", "invalid", "warning", "duplicate", "created", "skipped"]
CustomerRefundDisputeType = Literal[
    "order_not_received",
    "missing_item",
    "incorrect_item",
    "damaged_order",
    "quality_issue",
    "customer_refund",
    "order_error_adjustment",
    "chargeback",
    "unknown",
]
CustomerRefundDisputeReason = Literal[
    "customer_reported_not_received",
    "customer_reported_missing_item",
    "customer_reported_wrong_item",
    "customer_reported_quality_issue",
    "uber_adjustment_order_error",
    "refund_without_sufficient_proof",
    "self_delivery_dispute",
    "unknown_reason",
]
CustomerRefundDisputeStatus = Literal[
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
]
CustomerRefundEvidenceStatus = Literal["missing", "partial", "complete", "not_required", "manual_review"]
CustomerRefundRequirementStatus = Literal["pending", "uploaded", "waived", "not_available"]
RecoveryLossCategory = Literal[
    "cancellation_not_compensated",
    "customer_refund",
    "order_not_received",
    "missing_item",
    "incorrect_item",
    "order_error_adjustment",
    "chargeback",
    "manual_review",
]
RecoveryStage = Literal[
    "detected",
    "needs_evidence",
    "evidence_ready",
    "draft_created",
    "gmail_draft_created",
    "sent",
    "response_received",
    "accepted",
    "payment_to_verify",
    "payment_confirmed",
    "refused",
    "ignored",
    "manual_review",
    "under_appeal",
]
RecoveryCaseType = Literal["claim_order", "reconciliation_result", "customer_refund_dispute"]
RecoveryActionType = Literal[
    "upload_evidence",
    "create_claim_order",
    "create_draft",
    "create_gmail_draft",
    "process_response",
    "followup",
    "review_refusal",
    "create_appeal_draft",
    "request_more_evidence",
    "escalation",
    "manual_review",
]
EvidenceImportSourceType = Literal["multi_file_upload", "zip_upload", "mobile_upload", "server_folder_import"]
EvidenceImportBatchStatus = Literal[
    "uploaded",
    "extracting",
    "stored",
    "analyzing",
    "analyzed",
    "partially_analyzed",
    "failed",
    "cancelled",
]
EvidenceImportedFileStatus = Literal["stored", "analysis_pending", "analyzed", "failed", "ignored"]
EvidenceAnalysisProvider = Literal["local_ocr", "openai_vision", "fake"]
EvidenceAnalysisStatus = Literal["success", "partial", "failed", "manual_review"]
EvidenceAnalysisType = Literal[
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
    "unknown",
]
EvidenceMatchCandidateType = Literal["claim_order", "evidence_task", "customer_refund_dispute", "reconciliation_result"]
EvidenceMatchStatus = Literal["proposed", "auto_attached", "accepted", "rejected", "manual_review"]
EvidenceMatchReason = Literal[
    "exact_order_number",
    "display_id_match",
    "amount_date_restaurant_match",
    "restaurant_date_amount_match",
    "evidence_task_type_match",
    "filename_hint",
    "manual_selection",
    "low_confidence",
    "ambiguous_candidates",
]
EvidenceAttachmentDecisionType = Literal["attached", "rejected", "ignored", "deferred"]
AppealCaseType = Literal["claim_order", "customer_refund_dispute", "reconciliation_result"]
AppealWorkflowStatus = Literal[
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
]
AppealNextActionType = Literal[
    "review_refusal",
    "request_more_evidence",
    "create_appeal_draft",
    "create_gmail_draft",
    "send_manual_appeal",
    "escalation",
    "payment_verification",
    "manual_review",
]
AppealType = Literal[
    "first_appeal",
    "second_appeal",
    "escalation",
    "payment_verification",
    "evidence_reply",
    "manager_review",
]
AppealAttemptStatus = Literal["planned", "draft_created", "gmail_draft_created", "sent", "response_received", "superseded", "cancelled"]
RefusalSource = Literal["claim_response_review", "customer_refund_review", "inbound_message", "manual"]
RefusalNextAction = Literal[
    "provide_missing_evidence",
    "clarify_order_prepared",
    "clarify_delivery_proof",
    "challenge_generic_refusal",
    "request_escalation",
    "payment_verification",
    "manual_review",
]
AutopilotMode = Literal["initial_claims", "followups", "appeals", "all", "emergency_stop"]
AutopilotRunStatus = Literal["running", "completed", "failed", "stopped"]
AutopilotCaseType = Literal["claim_order", "followup_task", "appeal_workflow"]
AutopilotActionType = Literal[
    "send_initial_claim",
    "send_followup_1",
    "send_followup_2",
    "send_escalation",
    "send_appeal",
    "request_more_evidence",
    "manual_review",
]
AutopilotActionStatus = Literal[
    "candidate",
    "skipped",
    "draft_created",
    "provider_draft_created",
    "sent",
    "failed",
    "manual_review",
]
SmartImportCategory = Literal["uber_reporting", "evidence", "zip", "unknown"]
SmartImportRecommendedAction = Literal["import_uber_reporting", "import_evidence_bulk", "manual_review", "ignore"]
SmartImportFileStatus = Literal["previewed", "confirmed", "routed", "ignored", "failed", "expired", "manual_review"]
WorkspaceActionType = Literal[
    "upload_evidence",
    "review_import",
    "create_claim_order",
    "create_draft",
    "connect_gmail",
    "send_manual",
    "appeal_refusal",
    "map_uber_store",
    "review_customer_refund",
    "export_report",
    "manual_review",
]


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


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserRead


class RestaurantCreate(BaseModel):
    name: str = Field(min_length=1)
    legal_name: str | None = None
    address: str | None = None
    phone_number: str | None = None
    sender_email: str = Field(min_length=1)
    uber_merchant_id: str | None = None
    active: bool = True
    autopilot_enabled: bool = False


class RestaurantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    legal_name: str | None = None
    address: str | None = None
    phone_number: str | None = None
    sender_email: str | None = Field(default=None, min_length=1)
    uber_merchant_id: str | None = None
    active: bool | None = None
    autopilot_enabled: bool | None = None


class RestaurantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    address: str | None
    phone_number: str | None
    sender_email: str
    uber_merchant_id: str | None
    active: bool
    autopilot_enabled: bool
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
    provider: str | None = None
    provider_status: str | None = None
    provider_draft_id: str | None = None
    provider_message_id: str | None = None
    provider_sent_at: datetime | None = None
    provider_to_email: str | None = None


class EmailDraftSummaryRead(BaseModel):
    id: int
    order_id: int
    draft_type: EmailDraftType
    subject: str
    status: EmailDraftStatus
    created_at: datetime
    restaurant_name: str | None
    uber_order_number: str | None
    provider: str | None = None
    provider_status: str | None = None
    provider_draft_id: str | None = None
    provider_message_id: str | None = None
    provider_sent_at: datetime | None = None
    provider_to_email: str | None = None


class DashboardRestaurantSummary(BaseModel):
    restaurant_id: int
    restaurant_name: str
    total_orders: int
    total_claimed_amount: Decimal
    total_recovered_amount: Decimal


class DashboardTopRestaurantSummary(BaseModel):
    restaurant_id: int
    restaurant_name: str
    amount: Decimal


class DashboardSummary(BaseModel):
    total_orders: int
    total_claimed_amount: Decimal
    total_recovered_amount: Decimal
    total_pending_amount: Decimal
    total_refused_amount: Decimal
    accepted_count: int = 0
    payment_to_verify_count: int = 0
    payment_confirmed_count: int = 0
    refused_count: int = 0
    manual_review_count: int = 0
    pending_response_count: int = 0
    followups_due_count: int = 0
    followups_pending_count: int = 0
    escalations_due_count: int = 0
    manual_review_due_count: int = 0
    success_rate: Decimal = Decimal("0")
    top_restaurants_by_claimed_amount: list[DashboardTopRestaurantSummary] = Field(default_factory=list)
    top_restaurants_by_pending_amount: list[DashboardTopRestaurantSummary] = Field(default_factory=list)
    orders_by_status: dict[str, int]
    orders_by_restaurant: list[DashboardRestaurantSummary]


MissingClaimItem = Literal[
    "restaurant",
    "uber_order_number",
    "order_amount",
    "currency",
    "receipt",
    "cancellation_proof",
    "preparation_or_waste_proof",
]

ClaimValidationBlockingReason = Literal[
    "missing_restaurant",
    "missing_uber_order_number",
    "missing_order_amount",
    "missing_currency",
    "missing_unified_order_proof",
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


class EmailAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: EmailProviderName
    email_address: str | None
    connected_at: datetime
    disconnected_at: datetime | None


class GmailConnectionStatus(BaseModel):
    connected: bool
    email_address: str | None
    provider: EmailProviderName
    enabled: bool
    accounts: list[EmailAccountRead] = Field(default_factory=list)


class GmailOAuthStartResponse(BaseModel):
    authorization_url: str


class GmailRestaurantMappingRead(BaseModel):
    id: int | None
    restaurant_id: int
    restaurant_name: str
    email_account_id: int | None
    email_address: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GmailRestaurantMappingUpdate(BaseModel):
    email_account_id: int | None = None


class GmailDraftCreate(BaseModel):
    to_email: str | None = None
    include_evidence: bool = True


class GmailDraftSendRequest(BaseModel):
    confirm_send: bool


class ResendSendRequest(BaseModel):
    confirm_send: bool
    to_email: str | None = None
    include_evidence: bool = True


class GmailDraftSendResponse(BaseModel):
    provider_draft_id: str
    status: EmailProviderDraftStatus
    provider_message_id: str | None
    provider_thread_id: str | None
    sent_at: datetime | None


class GmailInboundStatusResponse(BaseModel):
    enabled: bool
    connected: bool
    last_sync_at: datetime | None
    last_success_at: datetime | None
    status: GmailSyncStatus | None
    last_error: str | None


class GmailInboundSyncRequest(BaseModel):
    lookback_days: int | None = Field(default=None, ge=1, le=365)
    max_messages: int | None = Field(default=None, ge=1, le=500)
    analyze_responses: bool = True
    apply_reviews: bool = True
    run_autopilot_after_sync: bool = True


class GmailInboundSyncResponse(BaseModel):
    status: GmailSyncStatus
    synced_messages: int
    linked_messages: int
    unlinked_messages: int
    ignored_messages: int
    analyzed_messages: int = 0
    applied_reviews: int = 0
    manual_review_messages: int = 0
    negative_responses_detected: int = 0
    autopilot_run_id: int | None = None
    autopilot_sent_count: int = 0
    autopilot_skipped_count: int = 0
    autopilot_failed_count: int = 0
    errors: list[str]


class GmailResponseAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inbound_message_id: int
    order_id: int | None
    response_review_id: int | None
    recommended_review_type: ClaimResponseReviewType
    status: GmailResponseAnalysisStatus
    confidence_score: Decimal | None
    reason: str | None
    detected_amount: Decimal | None
    expected_payment_date: date | None
    evidence_requested: bool | None
    matched_keywords_json: dict[str, Any] | None
    notes: str | None
    applied_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class GmailResponseAnalyzeRequest(BaseModel):
    apply_reviews: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    only_unreviewed: bool = True


class GmailResponseAnalyzeResponse(BaseModel):
    analyzed_messages: int
    applied_reviews: int
    manual_review_messages: int
    ignored_messages: int
    failed_messages: int
    errors: list[str]
    analyses: list[GmailResponseAnalysisRead]


class InboundEmailMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_account_id: int
    order_id: int | None
    provider: EmailProviderName
    provider_message_id: str
    provider_thread_id: str | None
    gmail_history_id: str | None
    from_email: str | None
    to_email: str | None
    subject: str | None
    snippet: str | None
    body_text: str | None
    received_at: datetime | None
    match_status: InboundEmailMatchStatus
    match_reason: InboundEmailMatchReason
    review_status: InboundEmailReviewStatus
    reviewed_at: datetime | None
    reviewed_by_user_id: int | None
    response_analysis: GmailResponseAnalysisRead | None = None
    created_at: datetime
    updated_at: datetime


class InboundMessagesResponse(BaseModel):
    messages: list[InboundEmailMessageRead]
    limit: int
    offset: int


class EmailThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    provider: str
    thread_id: str | None
    message_id: str | None
    direction: Literal["inbound", "outbound"]
    subject: str | None
    body: str | None
    ai_classification: str | None
    sent_at: datetime | None
    received_at: datetime | None
    created_at: datetime


class OrderEmailMessagesResponse(BaseModel):
    threads: list[EmailThreadRead]
    inbound_messages: list[InboundEmailMessageRead]


class InboundManualLinkRequest(BaseModel):
    order_id: int


class ClaimResponseReviewCreate(BaseModel):
    inbound_message_id: int | None = None
    review_type: ClaimResponseReviewType
    recovered_amount: Decimal | None = None
    expected_payment_date: date | None = None
    refusal_reason: str | None = None
    evidence_requested: bool | None = None
    notes: str | None = None


class ClaimResponseReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    inbound_message_id: int | None
    reviewed_by_user_id: int
    review_type: ClaimResponseReviewType
    previous_order_status: ClaimOrderStatus
    new_order_status: ClaimOrderStatus
    recovered_amount: Decimal | None
    expected_payment_date: date | None
    refusal_reason: str | None
    evidence_requested: bool | None
    notes: str | None
    order_status: ClaimOrderStatus
    created_at: datetime
    updated_at: datetime


class ResponseReviewsResponse(BaseModel):
    reviews: list[ClaimResponseReviewRead]
    limit: int
    offset: int


class ReportFilterEcho(BaseModel):
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    result: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    include_customer_names: bool = False


class CommercialTotals(BaseModel):
    orders_count: int
    total_claimed_amount: Decimal
    total_recovered_amount: Decimal
    total_pending_amount: Decimal
    total_refused_amount: Decimal
    average_claim_amount: Decimal
    success_rate: Decimal


class ReportBreakdownItem(BaseModel):
    key: str
    count: int
    claimed_amount: Decimal
    recovered_amount: Decimal


class CommercialRestaurantSummary(BaseModel):
    restaurant_id: int
    restaurant_name: str
    orders_count: int
    claimed_amount: Decimal
    recovered_amount: Decimal
    pending_amount: Decimal
    refused_amount: Decimal
    accepted_count: int
    refused_count: int
    manual_review_count: int


class CommercialFollowupSummary(BaseModel):
    due_count: int
    pending_count: int
    escalation_due_count: int
    manual_review_count: int


class CommercialResponseSummary(BaseModel):
    accepted_count: int
    refused_count: int
    payment_to_verify_count: int
    payment_confirmed_count: int
    manual_review_count: int


class CommercialCustomerRefundSummary(BaseModel):
    total_deducted_amount: Decimal = Decimal("0")
    total_recovered_amount: Decimal = Decimal("0")
    total_refused_amount: Decimal = Decimal("0")
    total_pending_amount: Decimal = Decimal("0")
    disputes_count: int = 0
    needs_evidence_count: int = 0
    evidence_ready_count: int = 0
    sent_count: int = 0
    accepted_count: int = 0
    refused_count: int = 0


class CommercialSummary(BaseModel):
    filters: ReportFilterEcho
    totals: CommercialTotals
    by_status: list[ReportBreakdownItem]
    by_result: list[ReportBreakdownItem]
    by_restaurant: list[CommercialRestaurantSummary]
    followups: CommercialFollowupSummary
    responses: CommercialResponseSummary
    customer_refunds: CommercialCustomerRefundSummary


class ReportOrderRow(BaseModel):
    order_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str
    customer_name: str | None = None
    order_date: date | None
    order_amount: Decimal | None
    currency: str
    status: ClaimOrderStatus
    result: str | None
    recovered_amount: Decimal | None
    retry_count: int
    last_followup_sent_at: datetime | None
    next_action_at: datetime | None
    evidence_count: int
    drafts_count: int
    inbound_messages_count: int
    response_reviews_count: int


class ReportOrdersResponse(BaseModel):
    orders: list[ReportOrderRow]
    limit: int
    offset: int


class ReportFollowupRow(BaseModel):
    task_id: int
    restaurant_name: str
    order_id: int
    uber_order_number: str
    task_type: FollowUpTaskType
    task_status: FollowUpTaskStatus
    due_at: datetime
    claim_status: ClaimOrderStatus
    order_amount: Decimal | None
    currency: str
    retry_count: int


class ReportFollowupsResponse(BaseModel):
    followups: list[ReportFollowupRow]
    limit: int
    offset: int


class ReportResponseRow(BaseModel):
    review_id: int
    restaurant_name: str
    order_id: int
    uber_order_number: str
    review_type: ClaimResponseReviewType
    previous_order_status: ClaimOrderStatus
    new_order_status: ClaimOrderStatus
    recovered_amount: Decimal | None
    refusal_reason: str | None
    evidence_requested: bool | None
    created_at: datetime
    reviewed_by_user_id: int


class ReportResponsesResponse(BaseModel):
    responses: list[ReportResponseRow]
    limit: int
    offset: int


class FollowUpTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    task_type: FollowUpTaskType
    status: FollowUpTaskStatus
    due_at: datetime
    generated_email_draft_id: int | None
    generated_provider_draft_id: int | None
    created_by_user_id: int | None
    completed_by_user_id: int | None
    skipped_by_user_id: int | None
    completed_at: datetime | None
    skipped_at: datetime | None
    skip_reason: str | None
    created_at: datetime
    updated_at: datetime


class FollowUpTaskSummary(BaseModel):
    id: int
    order_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str
    order_amount: Decimal | None
    currency: str
    claim_status: ClaimOrderStatus
    retry_count: int
    next_action_at: datetime | None
    last_followup_sent_at: datetime | None
    task_type: FollowUpTaskType
    status: FollowUpTaskStatus
    due_at: datetime
    generated_email_draft_id: int | None
    generated_provider_draft_id: int | None


class FollowUpsResponse(BaseModel):
    tasks: list[FollowUpTaskSummary]
    limit: int
    offset: int


class FollowUpRecalculateRequest(BaseModel):
    restaurant_id: int | None = None
    dry_run: bool = False


class FollowUpRecalculateResponse(BaseModel):
    created_tasks: int
    skipped_orders: int
    manual_review_orders: int
    errors: list[str]


class FollowUpSkipRequest(BaseModel):
    skip_reason: str = Field(min_length=1)


class EmailProviderDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_draft_id: int
    email_account_id: int | None
    provider: EmailProviderName
    provider_draft_id: str | None
    provider_thread_id: str | None
    provider_message_id: str | None
    to_email: str
    subject: str
    status: EmailProviderDraftStatus
    created_by_user_id: int
    sent_by_user_id: int | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    last_error: str | None


class UberStatusRead(BaseModel):
    provider: Literal["uber_eats"]
    status: UberIntegrationStatus
    official_api_enabled: bool = False
    approval_required: bool = True
    scopes: str | None = None
    store_mappings_count: int = 0


class UberStoreMappingCreate(BaseModel):
    restaurant_id: int
    uber_store_id: str | None = Field(default=None, min_length=1)
    uber_store_name: str = Field(min_length=1)
    merchant_store_id: str | None = None
    external_reference_id: str | None = None
    active: bool = True


class UberStoreMappingUpdate(BaseModel):
    uber_store_id: str | None = Field(default=None, min_length=1)
    uber_store_name: str | None = Field(default=None, min_length=1)
    merchant_store_id: str | None = None
    external_reference_id: str | None = None
    active: bool | None = None


class UberStoreMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    uber_store_id: str
    uber_store_name: str
    merchant_store_id: str | None
    external_reference_id: str | None
    active: bool
    created_at: datetime
    updated_at: datetime


class UberReportingImportResponse(BaseModel):
    snapshots_created: int
    transactions_created: int
    rows_skipped: int
    errors: list[str]


class UberReportingImportRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    row_number: int
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any] | None
    status: UberReportingRowStatus
    errors: list[str]
    warnings: list[str]
    created_snapshot_id: int | None
    created_transaction_id: int | None
    created_at: datetime


class UberReportingImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uploaded_by_user_id: int
    original_filename: str
    report_type: UberReportingReportType
    file_type: str
    status: UberReportingBatchStatus
    total_rows: int
    valid_rows: int
    invalid_rows: int
    warning_rows: int
    created_snapshots_count: int
    created_transactions_count: int
    duplicate_rows: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None


class UberReportingPreviewResponse(UberReportingImportBatchRead):
    batch_id: int
    unmapped_store_ids: list[str]
    detected_columns: list[str]
    rows_preview: list[UberReportingImportRowRead]


class UberReportingRowsResponse(BaseModel):
    rows: list[UberReportingImportRowRead]
    limit: int
    offset: int


class UberReportingConfirmResponse(BaseModel):
    batch_id: int
    status: UberReportingBatchStatus
    created_snapshots_count: int
    created_transactions_count: int
    skipped_rows: int
    errors: list[str]


class UberUnmappedStoreRead(BaseModel):
    uber_store_id: str
    uber_store_name: str | None
    row_count: int
    suggested_restaurant_matches: list[RestaurantRead] = Field(default_factory=list)


class UberUnmappedStoreMapRequest(BaseModel):
    restaurant_id: int


class UberHistoricalReclassificationRequest(BaseModel):
    restaurant_id: int | None = None
    min_confidence: Decimal = Field(default=Decimal("0.85"), ge=Decimal("0.85"), le=Decimal("1.00"))
    limit: int = Field(default=500, ge=1, le=5000)


class UberHistoricalReclassificationApplyRequest(UberHistoricalReclassificationRequest):
    confirm: bool = False


class UberHistoricalReclassificationLinkedUpdate(BaseModel):
    entity_type: str
    entity_id: int
    current_restaurant_id: int | None = None
    target_restaurant_id: int | None = None
    action: str | None = None
    status: str | None = None
    reason: str | None = None
    conflicting_entity_id: int | None = None
    from_restaurant_id: int | None = None
    to_restaurant_id: int | None = None
    linked_updates: list[dict[str, Any]] = Field(default_factory=list)


class UberHistoricalReclassificationCandidate(BaseModel):
    key: str
    entity_type: str
    entity_id: int
    uber_store_id: str | None = None
    uber_store_name: str | None = None
    uber_order_id: str | None = None
    display_id: str | None = None
    current_restaurant_id: int
    current_restaurant_name: str
    target_restaurant_id: int
    target_restaurant_name: str
    reason: str
    confidence: Decimal
    status: str
    blockers: list[str] = Field(default_factory=list)
    linked_updates: list[UberHistoricalReclassificationLinkedUpdate] = Field(default_factory=list)


class UberHistoricalReclassificationResponse(BaseModel):
    status: str
    total_candidates: int
    eligible_count: int
    blocked_count: int
    moved_count: int
    skipped_count: int
    candidates: list[UberHistoricalReclassificationCandidate]
    moved: list[UberHistoricalReclassificationCandidate] = Field(default_factory=list)
    skipped: list[UberHistoricalReclassificationCandidate] = Field(default_factory=list)
    run_by_user_id: int


class UberHistoricalImportRepairRequest(BaseModel):
    batch_id: int | None = None
    restaurant_id: int | None = None
    include_duplicates: bool = True
    min_confidence: Decimal = Field(default=Decimal("0.85"), ge=Decimal("0.85"), le=Decimal("1.00"))
    limit: int = Field(default=1000, ge=1, le=10000)


class UberHistoricalImportRepairApplyRequest(UberHistoricalImportRepairRequest):
    confirm: bool = False


class UberHistoricalImportRepairCandidate(BaseModel):
    key: str
    row_id: int
    batch_id: int
    row_number: int
    original_filename: str
    report_type: UberReportingReportType
    old_status: UberReportingRowStatus
    old_errors: list[str] = Field(default_factory=list)
    old_warnings: list[str] = Field(default_factory=list)
    new_errors: list[str] = Field(default_factory=list)
    new_warnings: list[str] = Field(default_factory=list)
    row_kind: str | None = None
    uber_store_id: str | None = None
    uber_store_name: str | None = None
    uber_order_id: str | None = None
    display_id: str | None = None
    target_restaurant_id: int | None = None
    target_restaurant_name: str | None = None
    reason: str
    confidence: Decimal
    status: str
    blockers: list[str] = Field(default_factory=list)
    created_snapshot_id: int | None = None
    created_transaction_id: int | None = None
    created_new_record: bool = False


class UberHistoricalImportRepairResponse(BaseModel):
    status: str
    scanned_count: int
    total_candidates: int
    eligible_count: int
    blocked_count: int
    repaired_count: int
    skipped_count: int
    created_snapshots_count: int
    created_transactions_count: int
    candidates: list[UberHistoricalImportRepairCandidate]
    repaired: list[UberHistoricalImportRepairCandidate] = Field(default_factory=list)
    skipped: list[UberHistoricalImportRepairCandidate] = Field(default_factory=list)
    run_by_user_id: int


class UberReconciliationRunRequest(BaseModel):
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    dry_run: bool = False


class UberReconciliationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_by_user_id: int
    restaurant_id: int | None
    date_from: date
    date_to: date
    status: UberReconciliationRunStatus
    total_orders_analyzed: int
    canceled_orders_count: int
    compensated_count: int
    not_compensated_count: int
    partially_compensated_count: int
    already_claimed_count: int
    needs_evidence_count: int
    manual_review_count: int
    total_claimable_amount: Decimal
    total_missing_amount: Decimal
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class UberReconciliationRunResponse(BaseModel):
    run_id: int
    status: UberReconciliationRunStatus
    total_orders_analyzed: int
    canceled_orders_count: int
    compensated_count: int
    not_compensated_count: int
    partially_compensated_count: int
    already_claimed_count: int
    needs_evidence_count: int
    manual_review_count: int
    total_claimable_amount: Decimal
    total_missing_amount: Decimal
    errors: list[str]


class UberReconciliationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    restaurant_id: int
    uber_order_id: str
    display_id: str | None
    claim_order_id: int | None
    status: UberReconciliationStatus
    financial_status: UberReconciliationFinancialStatus | None
    reason: str
    order_amount: Decimal | None
    paid_amount: Decimal
    refunded_amount: Decimal
    missing_amount: Decimal | None
    currency: str
    evidence_required: bool
    confidence_score: Decimal | None
    matched_transaction_ids_json: list[int] | None
    matched_snapshot_id: int | None
    created_at: datetime
    updated_at: datetime


class UberReconciliationResultsResponse(BaseModel):
    results: list[UberReconciliationResultRead]
    limit: int
    offset: int


class UberReconciliationSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    uber_store_id: str
    uber_order_id: str
    display_id: str | None
    current_state: str
    placed_at: datetime | None
    canceled_at: datetime | None
    order_total_amount: Decimal | None
    currency: str
    imported_from: UberImportedFrom
    created_at: datetime
    updated_at: datetime


class UberReconciliationTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    uber_store_id: str
    uber_order_id: str | None
    transaction_type: str
    amount: Decimal
    currency: str
    transaction_date: date
    payout_reference: str | None
    imported_from: UberImportedFrom
    created_at: datetime


class UberReconciliationResultDetail(BaseModel):
    result: UberReconciliationResultRead
    snapshot: UberReconciliationSnapshotRead | None
    transactions: list[UberReconciliationTransactionRead]
    claim_order: ClaimOrderRead | None


class UberReconciliationBulkCreateRequest(BaseModel):
    result_ids: list[int] = Field(min_length=1, max_length=500)


class UberReconciliationBulkCreateResponse(BaseModel):
    created_count: int
    skipped_count: int
    errors: list[str]
    created_order_ids: list[int]


class UberReconciliationIgnoreRequest(BaseModel):
    reason: str = Field(min_length=1)


class EvidenceRequestTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    reconciliation_result_id: int | None
    customer_refund_dispute_id: int | None
    restaurant_id: int
    task_type: EvidenceRequestTaskType
    required_evidence_type: EvidenceType
    status: EvidenceRequestTaskStatus
    priority: EvidenceRequestPriority
    title: str
    description: str | None
    due_at: datetime | None
    assigned_to_user_id: int | None
    reason: str
    created_by_user_id: int | None
    completed_by_user_id: int | None
    skipped_by_user_id: int | None
    completed_at: datetime | None
    skipped_at: datetime | None
    skip_reason: str | None
    last_upload_evidence_id: int | None
    created_at: datetime
    updated_at: datetime


class EvidenceRequestTaskSummary(BaseModel):
    id: int
    order_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str
    customer_name: str | None
    order_amount: Decimal | None
    currency: str
    claim_status: ClaimOrderStatus
    task_type: EvidenceRequestTaskType
    required_evidence_type: EvidenceType
    status: EvidenceRequestTaskStatus
    priority: EvidenceRequestPriority
    due_at: datetime | None
    title: str
    description: str | None
    reason: str
    reconciliation_result_id: int | None
    customer_refund_dispute_id: int | None
    last_upload_evidence_id: int | None
    created_at: datetime
    updated_at: datetime


class EvidenceRequestTasksResponse(BaseModel):
    tasks: list[EvidenceRequestTaskSummary]
    limit: int
    offset: int


class LiveEvidenceStationResponse(BaseModel):
    tasks: list[EvidenceRequestTaskSummary]
    recommended_task_id: int | None
    total_active_tasks: int
    pending_count: int
    uploaded_count: int
    urgent_count: int
    high_priority_count: int
    printer_mode: Literal["browser_print"]
    bluetooth_supported: bool
    native_print_modes: list[Literal["android_bluetooth_escpos"]]
    native_print_contract_version: str
    camera_capture_supported: bool
    native_printer_bridge_ready: bool
    native_printer_bridge_contract: str
    safe_capture_rules: list[str]
    limit: int
    offset: int


class EvidenceRequestRecalculateRequest(BaseModel):
    restaurant_id: int | None = None
    order_id: int | None = None
    dry_run: bool = False


class EvidenceRequestRecalculateResponse(BaseModel):
    created_tasks: int
    existing_tasks: int
    completed_tasks: int
    skipped_orders: int
    errors: list[str]


class EvidenceRequestSkipRequest(BaseModel):
    skip_reason: str = Field(min_length=1)


class EvidenceUploadLinkCreateRequest(BaseModel):
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    max_uses: int | None = Field(default=None, ge=1, le=20)


class EvidenceUploadLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    expires_at: datetime
    max_uses: int
    use_count: int
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EvidenceUploadLinkCreateResponse(EvidenceUploadLinkRead):
    token: str
    upload_url: str


class EvidencePrintTicketCreateRequest(BaseModel):
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    max_uses: int | None = Field(default=1, ge=1, le=20)


class EvidencePrintTicketResponse(BaseModel):
    task_id: int
    order_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str
    customer_name: str | None
    required_evidence_type: EvidenceType
    required_evidence_label: str
    title: str
    description: str | None
    order_amount: Decimal | None
    currency: str
    due_at: datetime | None
    ticket_reference: str
    upload_link: EvidenceUploadLinkRead
    upload_url: str
    qr_svg: str
    print_html: str


class PublicEvidenceUploadLinkRead(BaseModel):
    id: int
    task_id: int
    order_id: int
    restaurant_name: str
    uber_order_number: str
    customer_name: str | None
    task_type: EvidenceRequestTaskType
    required_evidence_type: EvidenceType
    status: EvidenceRequestTaskStatus
    priority: EvidenceRequestPriority
    due_at: datetime | None
    title: str
    description: str | None
    reason: str
    expires_at: datetime
    max_uses: int
    use_count: int


class EvidenceTaskUploadResponse(BaseModel):
    task: EvidenceRequestTaskRead
    evidence_file: EvidenceFileRead
    validation: ClaimValidationResponse


class CustomerRefundDetectRequest(BaseModel):
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None


class CustomerRefundDetectResponse(BaseModel):
    detected_count: int
    needs_evidence_count: int
    manual_review_count: int
    total_deducted_amount: Decimal
    errors: list[str]


class CustomerRefundEvidenceRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispute_id: int
    required_evidence_type: EvidenceType
    status: CustomerRefundRequirementStatus
    evidence_file_id: int | None
    created_at: datetime
    updated_at: datetime


class UberCustomerRefundDisputeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    uber_store_id: str | None
    uber_order_id: str | None
    display_id: str | None
    claim_order_id: int | None
    financial_transaction_id: int | None
    customer_refund_reference: str | None
    dispute_type: CustomerRefundDisputeType
    reason: CustomerRefundDisputeReason
    status: CustomerRefundDisputeStatus
    customer_refund_amount: Decimal
    order_amount: Decimal | None
    currency: str
    deducted_at: date | None
    order_date: date | None
    evidence_required: bool
    evidence_status: CustomerRefundEvidenceStatus
    dispute_email_draft_id: int | None
    provider_draft_id: int | None
    notes: str | None
    raw_payload_json: dict[str, Any] | None
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime
    ignored_at: datetime | None
    ignored_by_user_id: int | None
    ignore_reason: str | None
    recovered_amount: Decimal | None
    expected_payment_date: date | None
    last_reviewed_at: datetime | None
    last_reviewed_by_user_id: int | None


class CustomerRefundDisputeReviewCreate(BaseModel):
    inbound_message_id: int | None = None
    review_type: CustomerRefundReviewType
    recovered_amount: Decimal | None = None
    expected_payment_date: date | None = None
    refusal_reason: str | None = None
    evidence_requested: bool | None = None
    notes: str | None = None


class CustomerRefundDisputeReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dispute_id: int
    inbound_message_id: int | None
    reviewed_by_user_id: int
    review_type: CustomerRefundReviewType
    previous_dispute_status: CustomerRefundDisputeStatus
    new_dispute_status: CustomerRefundDisputeStatus
    previous_claim_order_status: ClaimOrderStatus | None
    new_claim_order_status: ClaimOrderStatus | None
    recovered_amount: Decimal | None
    expected_payment_date: date | None
    refusal_reason: str | None
    evidence_requested: bool | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class CustomerRefundDisputeReviewResponse(BaseModel):
    review: CustomerRefundDisputeReviewRead
    dispute_status: CustomerRefundDisputeStatus
    claim_order_status: ClaimOrderStatus | None


class CustomerRefundDisputeReviewsResponse(BaseModel):
    reviews: list[CustomerRefundDisputeReviewRead]
    limit: int
    offset: int


class CustomerRefundDisputeSummary(BaseModel):
    id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_id: str | None
    display_id: str | None
    claim_order_id: int | None
    dispute_type: CustomerRefundDisputeType
    reason: CustomerRefundDisputeReason
    status: CustomerRefundDisputeStatus
    customer_refund_amount: Decimal
    recovered_amount: Decimal | None = None
    expected_payment_date: date | None = None
    last_reviewed_at: datetime | None = None
    currency: str
    deducted_at: date | None
    evidence_status: CustomerRefundEvidenceStatus
    requirements_count: int
    pending_requirements_count: int
    created_at: datetime


class CustomerRefundDisputesResponse(BaseModel):
    disputes: list[CustomerRefundDisputeSummary]
    limit: int
    offset: int


class CustomerRefundDisputeDetail(BaseModel):
    dispute: UberCustomerRefundDisputeRead
    restaurant_name: str
    order_snapshot: dict[str, Any] | None
    financial_transaction: dict[str, Any] | None
    claim_order: ClaimOrderRead | None
    evidence_requirements: list[CustomerRefundEvidenceRequirementRead]
    evidence_files: list[EvidenceFileRead]
    evidence_tasks: list[EvidenceRequestTaskSummary]
    reviews: list[CustomerRefundDisputeReviewRead] = []


class CustomerRefundIgnoreRequest(BaseModel):
    reason: str = Field(min_length=1)


class CustomerRefundBulkRequest(BaseModel):
    dispute_ids: list[int] = Field(min_length=1, max_length=500)


class CustomerRefundBulkResponse(BaseModel):
    created_count: int
    skipped_count: int
    errors: list[str]
    created_ids: list[int]


class RecoveryFilterEcho(BaseModel):
    restaurant_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    loss_category: str | None = None
    include_ignored: bool = False


class RecoveryTotals(BaseModel):
    detected_amount: Decimal = Decimal("0")
    claimable_amount: Decimal = Decimal("0")
    missing_evidence_amount: Decimal = Decimal("0")
    sent_amount: Decimal = Decimal("0")
    recovered_amount: Decimal = Decimal("0")
    refused_amount: Decimal = Decimal("0")
    pending_amount: Decimal = Decimal("0")
    detected_count: int = 0
    claimable_count: int = 0
    missing_evidence_count: int = 0
    sent_count: int = 0
    recovered_count: int = 0
    refused_count: int = 0
    manual_review_count: int = 0
    active_appeals_count: int = 0
    appeal_needed_count: int = 0
    escalations_needed_count: int = 0
    refused_under_appeal_amount: Decimal = Decimal("0")
    manually_closed_amount: Decimal = Decimal("0")
    recovery_rate: Decimal = Decimal("0")
    review_coverage_rate: Decimal = Decimal("0")


class RecoveryBreakdownItem(BaseModel):
    key: str
    count: int
    detected_amount: Decimal = Decimal("0")
    claimable_amount: Decimal = Decimal("0")
    recovered_amount: Decimal = Decimal("0")
    refused_amount: Decimal = Decimal("0")


class RecoveryRestaurantBreakdownItem(RecoveryBreakdownItem):
    restaurant_id: int
    restaurant_name: str


class RecoveryCase(BaseModel):
    case_type: RecoveryCaseType
    case_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str | None
    customer_name: str | None = None
    loss_category: RecoveryLossCategory
    recovery_stage: RecoveryStage
    detected_amount: Decimal = Decimal("0")
    claimable_amount: Decimal = Decimal("0")
    recovered_amount: Decimal = Decimal("0")
    status: str
    evidence_status: str | None
    next_action: str | None
    created_at: datetime
    link_url: str


class RecoverySummary(BaseModel):
    filters: RecoveryFilterEcho
    totals: RecoveryTotals
    by_restaurant: list[RecoveryRestaurantBreakdownItem]
    by_loss_category: list[RecoveryBreakdownItem]
    by_recovery_stage: list[RecoveryBreakdownItem]
    top_recoverable_cases: list[RecoveryCase]


class RecoveryCasesResponse(BaseModel):
    cases: list[RecoveryCase]
    limit: int
    offset: int


class RecoveryAction(BaseModel):
    action_type: RecoveryActionType
    case_type: str
    case_id: int
    restaurant_name: str
    priority: str
    amount: Decimal = Decimal("0")
    due_at: datetime | None
    label: str
    url: str


class RecoveryActionsResponse(BaseModel):
    actions: list[RecoveryAction]
    limit: int
    offset: int


class WorkspaceAction(BaseModel):
    title: str
    description: str
    restaurant: str | None = None
    amount: Decimal | None = None
    priority: str
    action_url: str
    action_type: WorkspaceActionType


class WorkspaceNextActionsResponse(BaseModel):
    urgent: list[WorkspaceAction] = Field(default_factory=list)
    today: list[WorkspaceAction] = Field(default_factory=list)
    this_week: list[WorkspaceAction] = Field(default_factory=list)
    blocked: list[WorkspaceAction] = Field(default_factory=list)
    high_value: list[WorkspaceAction] = Field(default_factory=list)


class WorkspaceUnclassifiedItem(BaseModel):
    source_type: str
    source_id: int
    original_filename: str
    title: str
    description: str
    restaurant: str | None = None
    reason: str
    missing_fields: list[str] = Field(default_factory=list)
    action_url: str
    created_at: datetime


class WorkspaceUnclassifiedResponse(BaseModel):
    items: list[WorkspaceUnclassifiedItem] = Field(default_factory=list)
    total_count: int = 0


WorkspaceMachineTrigger = Literal["manual", "smart_import", "refunds", "cancellations"]


class WorkspaceMachineRunRequest(BaseModel):
    trigger: WorkspaceMachineTrigger = "manual"
    restaurant_id: int | None = None
    smart_import_batch_id: int | None = None
    sync_gmail: bool = True
    run_autopilot: bool = True


class WorkspaceMachineStage(BaseModel):
    name: str
    status: Literal["completed", "skipped", "warning", "failed"]
    processed_count: int = 0
    created_count: int = 0
    sent_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WorkspaceMachineRunResponse(BaseModel):
    status: Literal["completed", "warning", "failed"]
    trigger: WorkspaceMachineTrigger
    recipient_email: str
    stages: list[WorkspaceMachineStage]
    next_actions: WorkspaceNextActionsResponse


RecoveryMachineRailKey = Literal["refunds", "cancellations"]
RecoveryMachineStageKey = Literal[
    "smart_import",
    "evidence_needed",
    "evidence_received",
    "uber_emails",
    "followups",
    "payments",
]
RecoveryMachineStageStatus = Literal["empty", "ready", "attention", "working", "done"]


class RecoveryMachineStageRead(BaseModel):
    key: RecoveryMachineStageKey
    label: str
    description: str
    count: int = 0
    amount: Decimal = Decimal("0")
    status: RecoveryMachineStageStatus
    href: str


class RecoveryMachineRailRead(BaseModel):
    key: RecoveryMachineRailKey
    title: str
    short_title: str
    description: str
    href: str
    primary_action_label: str
    primary_action_href: str
    detected_count: int = 0
    detected_amount: Decimal = Decimal("0")
    claimable_amount: Decimal = Decimal("0")
    missing_evidence_count: int = 0
    evidence_ready_count: int = 0
    email_pipeline_count: int = 0
    followup_or_appeal_count: int = 0
    recovered_count: int = 0
    recovered_amount: Decimal = Decimal("0")
    progress_percent: int = 0
    health: Literal["empty", "good", "attention", "working"] = "empty"
    next_action_label: str
    next_action_href: str
    stages: list[RecoveryMachineStageRead]


class RecoveryMachineResponse(BaseModel):
    title: str = "Machine de recuperation"
    subtitle: str
    global_progress_percent: int = 0
    total_detected_amount: Decimal = Decimal("0")
    total_recovered_amount: Decimal = Decimal("0")
    total_actions_count: int = 0
    rails: list[RecoveryMachineRailRead]


class SmartImportFilePreviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_filename: str
    file_type: str
    detected_category: SmartImportCategory
    detected_report_type: str | None
    detected_evidence_type: str | None
    detected_restaurant_name: str | None
    detected_date_from: date | None
    detected_date_to: date | None
    header_row_number: int | None
    skipped_preamble_rows: int
    confidence: Decimal
    recommended_action: SmartImportRecommendedAction
    status: SmartImportFileStatus = "previewed"
    destination_type: str | None = None
    destination_id: int | None = None
    destination_url: str | None = None
    error_message: str | None = None
    warnings: list[str]
    detected_columns: list[str]
    metadata_json: dict[str, Any] | None = None


class SmartImportPreviewResponse(BaseModel):
    batch_preview_id: int
    status: str
    files: list[SmartImportFilePreviewRead]


class SmartImportFileDecision(BaseModel):
    file_id: int
    action: SmartImportRecommendedAction | None = None
    report_type: UberReportingReportType | None = None
    restaurant_id: int | None = None


class SmartImportConfirmRequest(BaseModel):
    batch_preview_id: int
    files: list[SmartImportFileDecision] = Field(default_factory=list)


class SmartImportRoutedFile(BaseModel):
    file_id: int
    original_filename: str
    action: SmartImportRecommendedAction
    destination_type: str | None = None
    destination_id: int | None = None
    destination_url: str | None = None
    processing_status: str | None = None
    created_snapshots_count: int | None = None
    created_transactions_count: int | None = None
    analyzed_files_count: int | None = None
    auto_matched_count: int | None = None
    needs_review_count: int | None = None
    skipped_rows: int | None = None
    processing_errors: list[str] = Field(default_factory=list)


class SmartImportConfirmError(BaseModel):
    file_id: int
    original_filename: str
    error: str


class SmartImportConfirmResponse(BaseModel):
    batch_preview_id: int
    status: str
    routed_files: list[SmartImportRoutedFile] = Field(default_factory=list)
    manual_review_files: list[SmartImportRoutedFile] = Field(default_factory=list)
    ignored_files: list[SmartImportRoutedFile] = Field(default_factory=list)
    errors: list[SmartImportConfirmError] = Field(default_factory=list)


class EvidenceImportBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uploaded_by_user_id: int
    restaurant_id: int | None
    original_filename: str | None
    source_type: EvidenceImportSourceType
    status: EvidenceImportBatchStatus
    total_files: int
    stored_files_count: int
    analyzed_files_count: int
    auto_matched_count: int
    needs_review_count: int
    failed_files_count: int
    duplicate_files_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class EvidenceImportedFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    uploaded_by_user_id: int
    original_filename: str
    internal_filename: str
    storage_backend: str
    mime_type: str | None
    file_size: int
    checksum_sha256: str
    page_count: int | None
    image_width: int | None
    image_height: int | None
    status: EvidenceImportedFileStatus
    created_at: datetime
    updated_at: datetime
    preview_url: str


class EvidenceAnalysisResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imported_file_id: int
    provider: EvidenceAnalysisProvider
    model_name: str | None
    status: EvidenceAnalysisStatus
    extracted_text: str | None
    detected_evidence_type: EvidenceAnalysisType
    detected_restaurant_name: str | None
    detected_uber_order_number: str | None
    detected_display_id: str | None
    detected_order_date: date | None
    detected_order_amount: Decimal | None
    detected_currency: str | None
    detected_keywords_json: list[str] | None
    classification_confidence: Decimal
    extraction_confidence: Decimal
    matching_confidence: Decimal
    raw_result_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class EvidenceMatchCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imported_file_id: int
    analysis_result_id: int
    candidate_type: EvidenceMatchCandidateType
    candidate_id: int
    restaurant_id: int | None
    match_reason: EvidenceMatchReason
    match_score: Decimal
    status: EvidenceMatchStatus
    created_at: datetime
    updated_at: datetime
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None


class EvidenceImportedFileDetail(BaseModel):
    file: EvidenceImportedFileRead
    analysis_results: list[EvidenceAnalysisResultRead]
    candidates: list[EvidenceMatchCandidateRead]


class EvidenceImportsResponse(BaseModel):
    batches: list[EvidenceImportBatchRead]
    limit: int
    offset: int


class EvidenceImportFilesResponse(BaseModel):
    files: list[EvidenceImportedFileRead]
    limit: int
    offset: int


class EvidenceImportAnalyzeRequest(BaseModel):
    provider: EvidenceAnalysisProvider = "fake"
    limit: int = Field(default=50, ge=1, le=500)


class EvidenceImportAnalyzeResponse(BaseModel):
    batch_id: int
    status: EvidenceImportBatchStatus
    analyzed_files_count: int
    auto_matched_count: int
    needs_review_count: int
    failed_files_count: int
    errors: list[str]


class EvidenceImportedFileAttachRequest(BaseModel):
    candidate_type: EvidenceMatchCandidateType
    candidate_id: int
    evidence_type: EvidenceType


class EvidenceAttachmentDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    imported_file_id: int
    evidence_file_id: int | None
    candidate_type: EvidenceMatchCandidateType
    candidate_id: int
    decision: EvidenceAttachmentDecisionType
    decided_by_user_id: int
    reason: str | None
    created_at: datetime


class EvidenceAttachResponse(BaseModel):
    decision: EvidenceAttachmentDecisionRead
    evidence_file: EvidenceFileRead | None
    validation: ClaimValidationResponse | None = None


class EvidenceCandidateRejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class EvidenceImportedFileIgnoreRequest(BaseModel):
    reason: str = Field(min_length=1)


class EvidenceBulkAcceptRequest(BaseModel):
    min_score: Decimal = Decimal("0.90")


class EvidenceBulkAcceptResponse(BaseModel):
    accepted_count: int
    skipped_count: int
    errors: list[str]


class AppealWorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_type: AppealCaseType
    case_id: int
    restaurant_id: int
    claim_order_id: int | None
    customer_refund_dispute_id: int | None
    reconciliation_result_id: int | None
    status: AppealWorkflowStatus
    current_level: int
    refusal_count: int
    appeal_attempt_count: int
    last_refusal_at: datetime | None
    last_appeal_sent_at: datetime | None
    next_action_at: datetime | None
    next_action_type: AppealNextActionType | None
    opened_by_user_id: int | None
    manually_closed_by_user_id: int | None
    manually_closed_at: datetime | None
    manual_close_reason: str | None
    created_at: datetime
    updated_at: datetime


class AppealAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    attempt_number: int
    appeal_type: AppealType
    status: AppealAttemptStatus
    based_on_refusal_message_id: int | None
    email_draft_id: int | None
    provider_draft_id: int | None
    sent_email_thread_id: int | None
    argument_summary: str | None
    new_evidence_summary: str | None
    created_by_user_id: int | None
    sent_by_user_id: int | None
    created_at: datetime
    sent_at: datetime | None
    completed_at: datetime | None


class RefusalAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    inbound_message_id: int | None
    review_id: int | None
    refusal_source: RefusalSource
    refusal_reason: str
    refusal_text_excerpt: str | None
    recommended_next_action: RefusalNextAction
    required_evidence_types_json: list[str] | None
    confidence: Decimal
    created_at: datetime


class AppealWorkflowSummary(BaseModel):
    id: int
    case_type: AppealCaseType
    case_id: int
    restaurant_id: int
    restaurant_name: str
    uber_order_number: str | None
    amount: Decimal
    currency: str
    status: AppealWorkflowStatus
    next_action_type: AppealNextActionType | None
    next_action_at: datetime | None
    refusal_count: int
    appeal_attempt_count: int
    created_at: datetime
    updated_at: datetime


class AppealsResponse(BaseModel):
    workflows: list[AppealWorkflowSummary]
    limit: int
    offset: int


class AppealDetailResponse(BaseModel):
    workflow: AppealWorkflowRead
    case_summary: dict[str, Any]
    attempts: list[AppealAttemptRead]
    refusal_analyses: list[RefusalAnalysisRead]
    evidence_tasks: list[EvidenceRequestTaskSummary]
    email_history: list[EmailDraftRead]


class AppealRecalculateRequest(BaseModel):
    restaurant_id: int | None = None


class AppealRecalculateResponse(BaseModel):
    created_workflows: int
    existing_workflows: int
    errors: list[str]


class AppealCreateDraftRequest(BaseModel):
    appeal_type: AppealType = "first_appeal"


class AppealPauseRequest(BaseModel):
    reason: str = Field(min_length=1)


class AppealManualCloseRequest(BaseModel):
    reason: str = Field(min_length=1)


class AutopilotRunRequest(BaseModel):
    mode: AutopilotMode = "all"
    restaurant_id: int | None = None
    dry_run: bool = True


class AutopilotSettingsRead(BaseModel):
    enabled: bool
    initial_claims_enabled: bool
    followups_enabled: bool
    appeals_enabled: bool
    daily_send_limit: int
    per_restaurant_daily_limit: int
    min_amount: Decimal
    max_amount_without_owner_review: Decimal
    require_complete_evidence: bool
    require_gmail_connected: bool
    cooldown_hours: int
    refusal_retry_enabled: bool
    max_appeal_attempts: int
    never_close_on_refusal: bool


class AutopilotStatusResponse(BaseModel):
    settings: AutopilotSettingsRead
    gmail_provider_enabled: bool
    gmail_connected: bool
    gmail_email_address: str | None
    emergency_stopped: bool
    sent_today_count: int
    remaining_today_count: int


class AutopilotRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_by_user_id: int | None
    status: AutopilotRunStatus
    mode: AutopilotMode
    total_candidates: int
    sent_count: int
    skipped_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None


class AutopilotActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    case_type: AutopilotCaseType
    case_id: int
    restaurant_id: int
    action_type: AutopilotActionType
    status: AutopilotActionStatus
    reason: str
    email_draft_id: int | None
    provider_draft_id: int | None
    sent_at: datetime | None
    skipped_reason: str | None
    created_at: datetime
    updated_at: datetime


class AutopilotRunDetailResponse(BaseModel):
    run: AutopilotRunRead
    actions: list[AutopilotActionRead]


class AutopilotRunsResponse(BaseModel):
    runs: list[AutopilotRunRead]
    limit: int
    offset: int


class AutopilotActionsResponse(BaseModel):
    actions: list[AutopilotActionRead]
    limit: int
    offset: int

