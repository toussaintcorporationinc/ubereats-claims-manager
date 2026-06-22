const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_STORAGE_KEY = "ubereats_claims_manager_token";
const REFRESH_TOKEN_STORAGE_KEY = "ubereats_claims_manager_refresh_token";
const SESSION_EXPIRED_STORAGE_KEY = "tennet_session_expired_message";

export const SESSION_EXPIRED_MESSAGE = "Votre session a expiré. Veuillez vous reconnecter.";
export const SESSION_EXPIRED_EVENT = "tennet:session-expired";

export type MoneyValue = string | number | null;
export type UserRole = "owner" | "manager" | "staff";

export type ClaimOrderStatus =
  | "draft"
  | "missing_evidence"
  | "ready_to_send"
  | "draft_email_created"
  | "sent"
  | "waiting_uber_response"
  | "response_received"
  | "followup_1_sent"
  | "followup_2_sent"
  | "escalation_sent"
  | "accepted"
  | "payment_to_verify"
  | "payment_confirmed"
  | "refused"
  | "manual_review"
  | "closed";

export type EvidenceType =
  | "receipt"
  | "cancellation_proof"
  | "preparation_proof"
  | "waste_photo"
  | "uber_screenshot"
  | "delivery_proof"
  | "packaging_photo"
  | "sealed_bag_photo"
  | "courier_statement"
  | "gps_or_route_proof"
  | "customer_contact_proof"
  | "order_details_screenshot"
  | "other";

export type EmailDraftType =
  | "initial_claim"
  | "followup_1"
  | "followup_2"
  | "escalation"
  | "proof_reply"
  | "customer_refund_order_not_received"
  | "customer_refund_missing_item"
  | "customer_refund_order_error_adjustment"
  | "customer_refund_generic"
  | "appeal_generic_refusal"
  | "appeal_missing_evidence_reply"
  | "appeal_order_prepared_before_cancellation"
  | "appeal_order_not_received_delivery_proof"
  | "appeal_missing_item_preparation_proof"
  | "appeal_escalation"
  | "appeal_payment_verification";
export type ImportBatchStatus = "uploaded" | "parsed" | "confirmed" | "partially_imported" | "failed" | "cancelled";
export type ImportRowStatus = "valid" | "invalid" | "duplicate" | "unauthorized" | "created" | "skipped";
export type EmailProviderDraftStatus = "provider_draft_created" | "send_requested" | "sent" | "failed";
export type EmailProviderName = "gmail" | "resend";
export type GmailSyncStatus = "idle" | "running" | "success" | "failed";
export type InboundEmailMatchStatus = "linked" | "unlinked" | "ignored";
export type InboundEmailReviewStatus = "unreviewed" | "reviewed" | "ignored";
export type GmailResponseAnalysisStatus = "analyzed" | "applied" | "manual_review" | "ignored" | "failed";
export type InboundEmailMatchReason =
  | "thread_id_match"
  | "order_number_match"
  | "subject_match"
  | "manual_link"
  | "no_match"
  | "ignored_sender";
export type ClaimResponseReviewType =
  | "accepted"
  | "payment_to_verify"
  | "payment_confirmed"
  | "refused"
  | "evidence_requested"
  | "information_requested"
  | "followup_needed"
  | "ignored"
  | "manual_review";
export type CustomerRefundReviewType = ClaimResponseReviewType;
export type FollowUpTaskType = "followup_1" | "followup_2" | "escalation" | "manual_review" | "payment_verification";
export type FollowUpTaskStatus =
  | "pending"
  | "draft_created"
  | "provider_draft_created"
  | "completed"
  | "skipped"
  | "cancelled";
export type EvidenceRequestTaskType =
  | "missing_receipt"
  | "missing_cancellation_proof"
  | "missing_preparation_proof"
  | "missing_waste_photo"
  | "missing_uber_screenshot"
  | "evidence_review";
export type EvidenceRequestTaskStatus = "pending" | "uploaded" | "completed" | "skipped" | "cancelled";
export type EvidenceRequestPriority = "low" | "normal" | "high" | "urgent";
export type UberIntegrationStatus = "not_configured" | "pending_approval" | "connected" | "disconnected" | "disabled";
export type UberReconciliationStatus =
  | "compensated"
  | "not_compensated"
  | "partially_compensated"
  | "needs_evidence"
  | "already_claimed"
  | "ignored"
  | "manual_review";
export type UberReconciliationFinancialStatus =
  | "compensated"
  | "not_compensated"
  | "partially_compensated"
  | "manual_review"
  | "not_cancelled";
export type UberReconciliationRunStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type UberReportingReportType = "orders_report" | "payments_report" | "adjustments_report" | "combined_report";
export type UberReportingBatchStatus = "uploaded" | "parsed" | "confirmed" | "partially_imported" | "failed" | "cancelled";
export type UberReportingRowStatus = "valid" | "invalid" | "warning" | "duplicate" | "created" | "skipped";
export type CustomerRefundDisputeType =
  | "order_not_received"
  | "missing_item"
  | "incorrect_item"
  | "damaged_order"
  | "quality_issue"
  | "customer_refund"
  | "order_error_adjustment"
  | "chargeback"
  | "unknown";
export type CustomerRefundDisputeReason =
  | "customer_reported_not_received"
  | "customer_reported_missing_item"
  | "customer_reported_wrong_item"
  | "customer_reported_quality_issue"
  | "uber_adjustment_order_error"
  | "refund_without_sufficient_proof"
  | "self_delivery_dispute"
  | "unknown_reason";
export type CustomerRefundDisputeStatus =
  | "detected"
  | "needs_evidence"
  | "evidence_ready"
  | "draft_created"
  | "gmail_draft_created"
  | "sent"
  | "accepted"
  | "payment_to_verify"
  | "payment_confirmed"
  | "refused"
  | "ignored"
  | "manual_review";
export type CustomerRefundEvidenceStatus = "missing" | "partial" | "complete" | "not_required" | "manual_review";
export type CustomerRefundRequirementStatus = "pending" | "uploaded" | "waived" | "not_available";
export type RecoveryLossCategory =
  | "cancellation_not_compensated"
  | "customer_refund"
  | "order_not_received"
  | "missing_item"
  | "incorrect_item"
  | "order_error_adjustment"
  | "chargeback"
  | "manual_review";
export type RecoveryStage =
  | "detected"
  | "needs_evidence"
  | "evidence_ready"
  | "draft_created"
  | "gmail_draft_created"
  | "sent"
  | "response_received"
  | "accepted"
  | "payment_to_verify"
  | "payment_confirmed"
  | "refused"
  | "ignored"
  | "manual_review"
  | "under_appeal";
export type RecoveryCaseType = "claim_order" | "reconciliation_result" | "customer_refund_dispute";
export type RecoveryActionType =
  | "upload_evidence"
  | "create_claim_order"
  | "create_draft"
  | "create_gmail_draft"
  | "process_response"
  | "followup"
  | "review_refusal"
  | "create_appeal_draft"
  | "request_more_evidence"
  | "escalation"
  | "manual_review";

export type EvidenceImportSourceType = "multi_file_upload" | "zip_upload" | "mobile_upload" | "server_folder_import";
export type EvidenceImportBatchStatus =
  | "uploaded"
  | "extracting"
  | "stored"
  | "analyzing"
  | "analyzed"
  | "partially_analyzed"
  | "failed"
  | "cancelled";
export type EvidenceImportedFileStatus = "stored" | "analysis_pending" | "analyzed" | "failed" | "ignored";
export type EvidenceAnalysisProvider = "fake" | "local_ocr" | "openai_vision";
export type EvidenceAnalysisStatus = "success" | "partial" | "failed" | "manual_review";
export type EvidenceAnalysisType = EvidenceType | "unknown";
export type EvidenceMatchCandidateType = "claim_order" | "evidence_task" | "customer_refund_dispute" | "reconciliation_result";
export type EvidenceMatchStatus = "proposed" | "auto_attached" | "accepted" | "rejected" | "manual_review";
export type EvidenceAttachmentDecisionType = "attached" | "rejected" | "ignored" | "deferred";
export type AppealCaseType = "claim_order" | "customer_refund_dispute" | "reconciliation_result";
export type AppealWorkflowStatus =
  | "active"
  | "appeal_needed"
  | "evidence_needed"
  | "draft_needed"
  | "gmail_draft_needed"
  | "appeal_sent"
  | "response_received"
  | "escalated"
  | "payment_to_verify"
  | "payment_confirmed"
  | "accepted"
  | "paused"
  | "manually_closed";
export type AppealNextActionType =
  | "review_refusal"
  | "request_more_evidence"
  | "create_appeal_draft"
  | "create_gmail_draft"
  | "send_manual_appeal"
  | "escalation"
  | "payment_verification"
  | "manual_review";
export type AppealType =
  | "first_appeal"
  | "second_appeal"
  | "escalation"
  | "payment_verification"
  | "evidence_reply"
  | "manager_review";
export type AppealAttemptStatus =
  | "planned"
  | "draft_created"
  | "gmail_draft_created"
  | "sent"
  | "response_received"
  | "superseded"
  | "cancelled";
export type AutopilotMode = "initial_claims" | "followups" | "appeals" | "all" | "emergency_stop";
export type AutopilotRunStatus = "running" | "completed" | "failed" | "stopped";
export type AutopilotCaseType = "claim_order" | "followup_task" | "appeal_workflow";
export type AutopilotActionType =
  | "send_initial_claim"
  | "send_followup_1"
  | "send_followup_2"
  | "send_escalation"
  | "send_appeal"
  | "request_more_evidence"
  | "manual_review";
export type AutopilotActionStatus =
  | "candidate"
  | "skipped"
  | "draft_created"
  | "provider_draft_created"
  | "sent"
  | "failed"
  | "manual_review";
export type SmartImportCategory = "uber_reporting" | "evidence" | "zip" | "unknown";
export type SmartImportRecommendedAction = "import_uber_reporting" | "import_evidence_bulk" | "manual_review" | "ignore";
export type WorkspaceActionType =
  | "upload_evidence"
  | "review_import"
  | "create_claim_order"
  | "create_draft"
  | "connect_gmail"
  | "send_manual"
  | "appeal_refusal"
  | "map_uber_store"
  | "review_customer_refund"
  | "export_report"
  | "manual_review";

export type Restaurant = {
  id: number;
  name: string;
  legal_name: string | null;
  address: string | null;
  phone_number: string | null;
  sender_email: string;
  uber_merchant_id: string | null;
  active: boolean;
  autopilot_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ClaimOrder = {
  id: number;
  restaurant_id: number;
  internal_reference: string | null;
  uber_order_number: string;
  customer_name: string | null;
  order_date: string | null;
  order_time: string | null;
  cancellation_time: string | null;
  order_amount: MoneyValue;
  currency: string;
  accepted_by_restaurant: boolean | null;
  prepared_before_cancellation: boolean | null;
  loss_type: string | null;
  status: ClaimOrderStatus;
  retry_count: number;
  first_email_sent_at: string | null;
  last_followup_sent_at: string | null;
  next_action_at: string | null;
  result: string | null;
  recovered_amount: MoneyValue;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceFile = {
  id: number;
  order_id: number;
  evidence_type: EvidenceType;
  original_filename: string;
  storage_path: string;
  storage_backend: string;
  mime_type: string | null;
  file_size: number | null;
  checksum_sha256: string | null;
  uploaded_by_user_id: number | null;
  uploaded_at: string;
  created_at: string;
  deleted_at: string | null;
  download_url: string | null;
};

export type EmailDraft = {
  id: number;
  order_id: number;
  draft_type: EmailDraftType;
  subject: string;
  body: string;
  status: string;
  provider: EmailProviderName | null;
  provider_status: string | null;
  provider_draft_id: string | null;
  provider_message_id: string | null;
  provider_sent_at: string | null;
  provider_to_email: string | null;
  created_at: string;
  updated_at: string;
};

export type EmailDraftSummary = {
  id: number;
  order_id: number;
  draft_type: EmailDraftType;
  subject: string;
  status: string;
  created_at: string;
  restaurant_name: string | null;
  uber_order_number: string | null;
  provider: EmailProviderName | null;
  provider_status: string | null;
  provider_draft_id: string | null;
  provider_message_id: string | null;
  provider_sent_at: string | null;
  provider_to_email: string | null;
};

export type GmailConnectionStatus = {
  connected: boolean;
  email_address: string | null;
  provider: EmailProviderName;
  enabled: boolean;
  accounts: EmailAccount[];
};

export type EmailAccount = {
  id: number;
  provider: EmailProviderName;
  email_address: string | null;
  connected_at: string;
  disconnected_at: string | null;
};

export type GmailRestaurantMapping = {
  id: number | null;
  restaurant_id: number;
  restaurant_name: string;
  email_account_id: number | null;
  email_address: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type GmailOAuthStartResponse = {
  authorization_url: string;
};

export type GmailDraftCreatePayload = {
  to_email?: string | null;
  include_evidence: boolean;
};

export type GmailDraftSendPayload = {
  confirm_send: boolean;
};

export type ResendSendPayload = {
  confirm_send: boolean;
  to_email?: string | null;
  include_evidence: boolean;
};

export type GmailDraftSendResponse = {
  provider_draft_id: string;
  status: EmailProviderDraftStatus;
  provider_message_id: string | null;
  provider_thread_id: string | null;
  sent_at: string | null;
};

export type GmailWorkerCycleSummary = {
  created_at: string;
  accounts_checked: number;
  accounts_synced: number;
  accounts_skipped: number;
  synced_messages: number;
  applied_reviews: number;
  negative_responses_detected: number;
  autopilot_sent_count: number;
  autopilot_skipped_count: number;
  autopilot_failed_count: number;
  workspace_machine_runs: number;
  errors: string[];
};

export type GmailWorkerBlockerSummary = {
  action_type: string;
  skipped_reason: string;
  count: number;
};

export type GmailInboundStatus = {
  enabled: boolean;
  connected: boolean;
  auto_sync_enabled: boolean;
  auto_sync_continuous_enabled: boolean;
  auto_sync_interval_seconds: number | null;
  auto_sync_run_autopilot: boolean;
  auto_sync_run_workspace_machine: boolean;
  autopilot_enabled: boolean;
  autopilot_initial_claims_enabled: boolean;
  autopilot_followups_enabled: boolean;
  autopilot_appeals_enabled: boolean;
  autopilot_require_complete_restaurant_signature: boolean;
  ai_gmail_analysis_enabled: boolean;
  connected_accounts_count: number;
  connected_account_emails: string[];
  last_sync_at: string | null;
  last_success_at: string | null;
  next_sync_at: string | null;
  seconds_until_next_sync: number | null;
  worker_state: "active" | "attention" | "disabled" | string;
  worker_message: string | null;
  last_cycle: GmailWorkerCycleSummary | null;
  last_autopilot_blockers: GmailWorkerBlockerSummary[];
  status: GmailSyncStatus | null;
  last_error: string | null;
};

export type GmailRelanceOrderSummary = {
  order_id: number | null;
  restaurant_id: number | null;
  restaurant_name: string | null;
  uber_order_number: string | null;
  customer_name: string | null;
  order_date: string | null;
  order_amount: MoneyValue;
  currency: string | null;
  status: string | null;
};

export type GmailRelanceSummary = {
  connected_accounts_count: number;
  starred_threads_seen: number;
  unlinked_starred_threads: number;
  sent_relances_last_24h: number;
  blocked_actions_last_24h: number;
  payment_signals_last_24h: number;
  latest_cycle_sent_count: number;
  latest_cycle_skipped_count: number;
  latest_cycle_failed_count: number;
};

export type GmailRelanceMessageItem = {
  id: number;
  email_account_id: number;
  account_email: string | null;
  provider_thread_id: string | null;
  provider_message_id: string;
  subject: string | null;
  from_email: string | null;
  to_email: string | null;
  snippet: string | null;
  received_at: string | null;
  is_starred: boolean;
  match_status: string;
  match_reason: string;
  review_status: string;
  order: GmailRelanceOrderSummary | null;
  analysis_type: string | null;
  analysis_status: string | null;
  analysis_reason: string | null;
  detected_amount: MoneyValue;
  created_at: string;
  updated_at: string;
};

export type GmailRelanceSentItem = {
  id: number;
  email_account_id: number | null;
  account_email: string | null;
  provider_thread_id: string | null;
  provider_message_id: string | null;
  to_email: string;
  subject: string;
  status: string;
  sent_at: string | null;
  error_message: string | null;
  last_error: string | null;
  order: GmailRelanceOrderSummary | null;
  created_at: string;
  updated_at: string;
};

export type GmailRelanceActionItem = {
  id: number;
  run_id: number;
  case_type: string;
  case_id: number;
  restaurant_id: number;
  restaurant_name: string | null;
  action_type: string;
  status: string;
  reason: string;
  skipped_reason: string | null;
  email_draft_id: number | null;
  provider_draft_id: number | null;
  sent_at: string | null;
  order: GmailRelanceOrderSummary | null;
  created_at: string;
  updated_at: string;
};

export type GmailRelanceDashboard = {
  updated_at: string;
  worker: GmailInboundStatus;
  summary: GmailRelanceSummary;
  starred_threads: GmailRelanceMessageItem[];
  sent_relances: GmailRelanceSentItem[];
  recent_actions: GmailRelanceActionItem[];
};

export type GmailInboundSyncPayload = {
  lookback_days?: number;
  max_messages?: number;
  analyze_responses?: boolean;
  apply_reviews?: boolean;
  run_autopilot_after_sync?: boolean;
};

export type GmailInboundSyncResponse = {
  status: GmailSyncStatus;
  synced_messages: number;
  linked_messages: number;
  unlinked_messages: number;
  ignored_messages: number;
  analyzed_messages: number;
  applied_reviews: number;
  manual_review_messages: number;
  negative_responses_detected: number;
  autopilot_run_id: number | null;
  autopilot_sent_count: number;
  autopilot_skipped_count: number;
  autopilot_failed_count: number;
  errors: string[];
};

export type GmailResponseAnalysis = {
  id: number;
  inbound_message_id: number;
  order_id: number | null;
  response_review_id: number | null;
  recommended_review_type: ClaimResponseReviewType;
  status: GmailResponseAnalysisStatus;
  confidence_score: string | number | null;
  reason: string | null;
  detected_amount: MoneyValue;
  expected_payment_date: string | null;
  evidence_requested: boolean | null;
  matched_keywords_json: Record<string, string[]> | null;
  notes: string | null;
  applied_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type GmailResponseAnalyzePayload = {
  apply_reviews?: boolean;
  limit?: number;
  only_unreviewed?: boolean;
};

export type GmailResponseAnalyzeResponse = {
  analyzed_messages: number;
  applied_reviews: number;
  manual_review_messages: number;
  ignored_messages: number;
  failed_messages: number;
  errors: string[];
  analyses: GmailResponseAnalysis[];
};

export type InboundEmailMessage = {
  id: number;
  email_account_id: number;
  order_id: number | null;
  provider: EmailProviderName;
  provider_message_id: string;
  provider_thread_id: string | null;
  gmail_history_id: string | null;
  from_email: string | null;
  to_email: string | null;
  subject: string | null;
  snippet: string | null;
  body_text: string | null;
  received_at: string | null;
  match_status: InboundEmailMatchStatus;
  match_reason: InboundEmailMatchReason;
  review_status: InboundEmailReviewStatus;
  reviewed_at: string | null;
  reviewed_by_user_id: number | null;
  response_analysis: GmailResponseAnalysis | null;
  created_at: string;
  updated_at: string;
};

export type InboundMessagesResponse = {
  messages: InboundEmailMessage[];
  limit: number;
  offset: number;
};

export type EmailThread = {
  id: number;
  order_id: number;
  provider: string;
  thread_id: string | null;
  message_id: string | null;
  direction: "inbound" | "outbound";
  subject: string | null;
  body: string | null;
  ai_classification: string | null;
  sent_at: string | null;
  received_at: string | null;
  created_at: string;
};

export type OrderEmailMessagesResponse = {
  threads: EmailThread[];
  inbound_messages: InboundEmailMessage[];
};

export type EmailProviderDraft = {
  id: number;
  email_draft_id: number;
  email_account_id: number | null;
  provider: "gmail";
  provider_draft_id: string | null;
  provider_thread_id: string | null;
  provider_message_id: string | null;
  to_email: string;
  subject: string;
  status: EmailProviderDraftStatus;
  created_by_user_id: number;
  sent_by_user_id: number | null;
  sent_at: string | null;
  error_message: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

export type DashboardRestaurantSummary = {
  restaurant_id: number;
  restaurant_name: string;
  total_orders: number;
  total_claimed_amount: MoneyValue;
  total_recovered_amount: MoneyValue;
};

export type DashboardTopRestaurantSummary = {
  restaurant_id: number;
  restaurant_name: string;
  amount: MoneyValue;
};

export type DashboardSummary = {
  total_orders: number;
  total_claimed_amount: MoneyValue;
  total_recovered_amount: MoneyValue;
  total_pending_amount: MoneyValue;
  total_refused_amount: MoneyValue;
  accepted_count: number;
  payment_to_verify_count: number;
  payment_confirmed_count: number;
  refused_count: number;
  manual_review_count: number;
  pending_response_count: number;
  followups_due_count: number;
  followups_pending_count: number;
  escalations_due_count: number;
  manual_review_due_count: number;
  success_rate: MoneyValue;
  top_restaurants_by_claimed_amount: DashboardTopRestaurantSummary[];
  top_restaurants_by_pending_amount: DashboardTopRestaurantSummary[];
  orders_by_status: Record<string, number>;
  orders_by_restaurant: DashboardRestaurantSummary[];
};

export type ReportFilters = {
  restaurant_id?: number | "";
  date_from?: string;
  date_to?: string;
  status?: string;
  result?: string;
  min_amount?: string;
  max_amount?: string;
  include_customer_names?: boolean;
  limit?: number;
  offset?: number;
};

export type ReportFilterEcho = {
  restaurant_id: number | null;
  date_from: string | null;
  date_to: string | null;
  status: string | null;
  result: string | null;
  min_amount: MoneyValue;
  max_amount: MoneyValue;
  include_customer_names: boolean;
};

export type CommercialTotals = {
  orders_count: number;
  total_claimed_amount: MoneyValue;
  total_recovered_amount: MoneyValue;
  total_pending_amount: MoneyValue;
  total_refused_amount: MoneyValue;
  average_claim_amount: MoneyValue;
  success_rate: MoneyValue;
};

export type ReportBreakdownItem = {
  key: string;
  count: number;
  claimed_amount: MoneyValue;
  recovered_amount: MoneyValue;
};

export type CommercialRestaurantSummary = {
  restaurant_id: number;
  restaurant_name: string;
  orders_count: number;
  claimed_amount: MoneyValue;
  recovered_amount: MoneyValue;
  pending_amount: MoneyValue;
  refused_amount: MoneyValue;
  accepted_count: number;
  refused_count: number;
  manual_review_count: number;
};

export type CommercialCustomerRefundSummary = {
  total_deducted_amount: MoneyValue;
  total_recovered_amount: MoneyValue;
  total_refused_amount: MoneyValue;
  total_pending_amount: MoneyValue;
  disputes_count: number;
  needs_evidence_count: number;
  evidence_ready_count: number;
  sent_count: number;
  accepted_count: number;
  refused_count: number;
};

export type CommercialSummary = {
  filters: ReportFilterEcho;
  totals: CommercialTotals;
  by_status: ReportBreakdownItem[];
  by_result: ReportBreakdownItem[];
  by_restaurant: CommercialRestaurantSummary[];
  followups: {
    due_count: number;
    pending_count: number;
    escalation_due_count: number;
    manual_review_count: number;
  };
  responses: {
    accepted_count: number;
    refused_count: number;
    payment_to_verify_count: number;
    payment_confirmed_count: number;
    manual_review_count: number;
  };
  customer_refunds: CommercialCustomerRefundSummary;
};

export type ReportOrderRow = {
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  customer_name?: string | null;
  order_date: string | null;
  order_amount: MoneyValue;
  currency: string;
  status: ClaimOrderStatus;
  result: string | null;
  recovered_amount: MoneyValue;
  retry_count: number;
  last_followup_sent_at: string | null;
  next_action_at: string | null;
  evidence_count: number;
  drafts_count: number;
  inbound_messages_count: number;
  response_reviews_count: number;
};

export type ReportOrdersResponse = {
  orders: ReportOrderRow[];
  limit: number;
  offset: number;
};

export type ReportFollowupRow = {
  task_id: number;
  restaurant_name: string;
  order_id: number;
  uber_order_number: string;
  task_type: FollowUpTaskType;
  task_status: FollowUpTaskStatus;
  due_at: string;
  claim_status: ClaimOrderStatus;
  order_amount: MoneyValue;
  currency: string;
  retry_count: number;
};

export type ReportFollowupsResponse = {
  followups: ReportFollowupRow[];
  limit: number;
  offset: number;
};

export type ReportResponseRow = {
  review_id: number;
  restaurant_name: string;
  order_id: number;
  uber_order_number: string;
  review_type: ClaimResponseReviewType;
  previous_order_status: ClaimOrderStatus;
  new_order_status: ClaimOrderStatus;
  recovered_amount: MoneyValue;
  refusal_reason: string | null;
  evidence_requested: boolean | null;
  created_at: string;
  reviewed_by_user_id: number;
};

export type ReportResponsesResponse = {
  responses: ReportResponseRow[];
  limit: number;
  offset: number;
};

export type ClaimResponseReview = {
  id: number;
  order_id: number;
  inbound_message_id: number | null;
  reviewed_by_user_id: number;
  review_type: ClaimResponseReviewType;
  previous_order_status: ClaimOrderStatus;
  new_order_status: ClaimOrderStatus;
  recovered_amount: MoneyValue;
  expected_payment_date: string | null;
  refusal_reason: string | null;
  evidence_requested: boolean | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type ClaimResponseReviewCreatePayload = {
  inbound_message_id?: number | null;
  review_type: ClaimResponseReviewType;
  recovered_amount?: string | null;
  expected_payment_date?: string | null;
  refusal_reason?: string | null;
  evidence_requested?: boolean | null;
  notes?: string | null;
};

export type ResponseReviewsResponse = {
  reviews: ClaimResponseReview[];
  limit: number;
  offset: number;
};

export type FollowUpTask = {
  id: number;
  order_id: number;
  task_type: FollowUpTaskType;
  status: FollowUpTaskStatus;
  due_at: string;
  generated_email_draft_id: number | null;
  generated_provider_draft_id: number | null;
  created_by_user_id: number | null;
  completed_by_user_id: number | null;
  skipped_by_user_id: number | null;
  completed_at: string | null;
  skipped_at: string | null;
  skip_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type FollowUpTaskSummary = {
  id: number;
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  customer_name: string | null;
  order_amount: MoneyValue;
  currency: string;
  claim_status: ClaimOrderStatus;
  retry_count: number;
  next_action_at: string | null;
  last_followup_sent_at: string | null;
  task_type: FollowUpTaskType;
  status: FollowUpTaskStatus;
  due_at: string;
  generated_email_draft_id: number | null;
  generated_provider_draft_id: number | null;
};

export type FollowUpsResponse = {
  tasks: FollowUpTaskSummary[];
  limit: number;
  offset: number;
};

export type FollowUpRecalculatePayload = {
  restaurant_id?: number | null;
  dry_run?: boolean;
};

export type FollowUpRecalculateResponse = {
  created_tasks: number;
  skipped_orders: number;
  manual_review_orders: number;
  errors: string[];
};

export type EvidenceRequestTask = {
  id: number;
  order_id: number;
  reconciliation_result_id: number | null;
  customer_refund_dispute_id: number | null;
  restaurant_id: number;
  task_type: EvidenceRequestTaskType;
  required_evidence_type: EvidenceType;
  status: EvidenceRequestTaskStatus;
  priority: EvidenceRequestPriority;
  title: string;
  description: string | null;
  due_at: string | null;
  assigned_to_user_id: number | null;
  reason: string;
  created_by_user_id: number | null;
  completed_by_user_id: number | null;
  skipped_by_user_id: number | null;
  completed_at: string | null;
  skipped_at: string | null;
  skip_reason: string | null;
  last_upload_evidence_id: number | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceRequestTaskSummary = {
  id: number;
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  customer_name: string | null;
  order_date: string | null;
  order_time: string | null;
  order_amount: MoneyValue;
  currency: string;
  claim_status: ClaimOrderStatus;
  task_type: EvidenceRequestTaskType;
  required_evidence_type: EvidenceType;
  status: EvidenceRequestTaskStatus;
  priority: EvidenceRequestPriority;
  due_at: string | null;
  title: string;
  description: string | null;
  reason: string;
  reconciliation_result_id: number | null;
  customer_refund_dispute_id: number | null;
  last_upload_evidence_id: number | null;
  field_context_label: string;
  field_restaurant_label: string;
  field_customer_label: string;
  field_order_label: string;
  field_date_label: string;
  field_amount_label: string;
  field_search_hint: string;
  field_photo_instruction: string;
  field_missing_info: string[];
  created_at: string;
  updated_at: string;
};

export type EvidenceRequestTasksResponse = {
  tasks: EvidenceRequestTaskSummary[];
  limit: number;
  offset: number;
};

export type LiveEvidenceStationResponse = {
  tasks: EvidenceRequestTaskSummary[];
  recommended_task_id: number | null;
  total_active_tasks: number;
  pending_count: number;
  uploaded_count: number;
  urgent_count: number;
  high_priority_count: number;
  printer_mode: "browser_print";
  bluetooth_supported: boolean;
  native_print_modes: "android_bluetooth_escpos"[];
  native_print_contract_version: string;
  camera_capture_supported: boolean;
  native_printer_bridge_ready: boolean;
  native_printer_bridge_contract: string;
  safe_capture_rules: string[];
  limit: number;
  offset: number;
};

export type EvidenceRequestRecalculatePayload = {
  restaurant_id?: number | null;
  order_id?: number | null;
  dry_run?: boolean;
};

export type EvidenceRequestRecalculateResponse = {
  created_tasks: number;
  existing_tasks: number;
  completed_tasks: number;
  skipped_orders: number;
  errors: string[];
};

export type EvidenceUploadLink = {
  id: number;
  task_id: number;
  expires_at: string;
  max_uses: number;
  use_count: number;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceUploadLinkCreateResponse = EvidenceUploadLink & {
  token: string;
  upload_url: string;
};

export type EvidencePrintTicketResponse = {
  task_id: number;
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  customer_name: string | null;
  required_evidence_type: EvidenceType;
  required_evidence_label: string;
  title: string;
  description: string | null;
  order_amount: MoneyValue;
  currency: string;
  due_at: string | null;
  ticket_reference: string;
  upload_link: EvidenceUploadLink;
  upload_url: string;
  qr_svg: string;
  print_html: string;
};

export type PublicEvidenceUploadLink = {
  id: number;
  task_id: number;
  order_id: number;
  restaurant_name: string;
  uber_order_number: string;
  customer_name: string | null;
  task_type: EvidenceRequestTaskType;
  required_evidence_type: EvidenceType;
  status: EvidenceRequestTaskStatus;
  priority: EvidenceRequestPriority;
  due_at: string | null;
  title: string;
  description: string | null;
  reason: string;
  expires_at: string;
  max_uses: number;
  use_count: number;
};

export type EvidenceTaskUploadResponse = {
  task: EvidenceRequestTask;
  evidence_file: EvidenceFile;
  validation: ClaimValidationResponse;
};

export type CustomerRefundDetectPayload = {
  restaurant_id?: number | null;
  date_from?: string | null;
  date_to?: string | null;
};

export type CustomerRefundDetectResponse = {
  detected_count: number;
  needs_evidence_count: number;
  manual_review_count: number;
  total_deducted_amount: MoneyValue;
  errors: string[];
};

export type CustomerRefundEvidenceRequirement = {
  id: number;
  dispute_id: number;
  required_evidence_type: EvidenceType;
  status: CustomerRefundRequirementStatus;
  evidence_file_id: number | null;
  created_at: string;
  updated_at: string;
};

export type UberCustomerRefundDispute = {
  id: number;
  restaurant_id: number;
  uber_store_id: string | null;
  uber_order_id: string | null;
  display_id: string | null;
  claim_order_id: number | null;
  financial_transaction_id: number | null;
  customer_refund_reference: string | null;
  dispute_type: CustomerRefundDisputeType;
  reason: CustomerRefundDisputeReason;
  status: CustomerRefundDisputeStatus;
  customer_refund_amount: MoneyValue;
  order_amount: MoneyValue;
  recovered_amount: MoneyValue;
  expected_payment_date: string | null;
  last_reviewed_at: string | null;
  last_reviewed_by_user_id: number | null;
  currency: string;
  deducted_at: string | null;
  order_date: string | null;
  evidence_required: boolean;
  evidence_status: CustomerRefundEvidenceStatus;
  dispute_email_draft_id: number | null;
  provider_draft_id: number | null;
  notes: string | null;
  raw_payload_json: Record<string, unknown> | null;
  created_by_user_id: number | null;
  created_at: string;
  updated_at: string;
  ignored_at: string | null;
  ignored_by_user_id: number | null;
  ignore_reason: string | null;
};

export type CustomerRefundDisputeSummary = {
  id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_id: string | null;
  display_id: string | null;
  claim_order_id: number | null;
  dispute_type: CustomerRefundDisputeType;
  reason: CustomerRefundDisputeReason;
  status: CustomerRefundDisputeStatus;
  customer_refund_amount: MoneyValue;
  recovered_amount: MoneyValue;
  expected_payment_date: string | null;
  last_reviewed_at: string | null;
  currency: string;
  deducted_at: string | null;
  evidence_status: CustomerRefundEvidenceStatus;
  requirements_count: number;
  pending_requirements_count: number;
  created_at: string;
};

export type CustomerRefundDisputesResponse = {
  disputes: CustomerRefundDisputeSummary[];
  limit: number;
  offset: number;
};

export type CustomerRefundDisputeDetail = {
  dispute: UberCustomerRefundDispute;
  restaurant_name: string;
  order_snapshot: Record<string, unknown> | null;
  financial_transaction: Record<string, unknown> | null;
  claim_order: ClaimOrder | null;
  evidence_requirements: CustomerRefundEvidenceRequirement[];
  evidence_files: EvidenceFile[];
  evidence_tasks: EvidenceRequestTaskSummary[];
  reviews: CustomerRefundDisputeReview[];
};

export type CustomerRefundBulkResponse = {
  created_count: number;
  skipped_count: number;
  errors: string[];
  created_ids: number[];
};

export type CustomerRefundDisputeReview = {
  id: number;
  dispute_id: number;
  inbound_message_id: number | null;
  reviewed_by_user_id: number;
  review_type: CustomerRefundReviewType;
  previous_dispute_status: CustomerRefundDisputeStatus;
  new_dispute_status: CustomerRefundDisputeStatus;
  previous_claim_order_status: ClaimOrderStatus | null;
  new_claim_order_status: ClaimOrderStatus | null;
  recovered_amount: MoneyValue;
  expected_payment_date: string | null;
  refusal_reason: string | null;
  evidence_requested: boolean | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type CustomerRefundDisputeReviewPayload = {
  inbound_message_id?: number | null;
  review_type: CustomerRefundReviewType;
  recovered_amount?: string | null;
  expected_payment_date?: string | null;
  refusal_reason?: string | null;
  evidence_requested?: boolean | null;
  notes?: string | null;
};

export type CustomerRefundDisputeReviewResponse = {
  review: CustomerRefundDisputeReview;
  dispute_status: CustomerRefundDisputeStatus;
  claim_order_status: ClaimOrderStatus | null;
};

export type CustomerRefundDisputeReviewsResponse = {
  reviews: CustomerRefundDisputeReview[];
  limit: number;
  offset: number;
};

export type RecoveryFilters = {
  restaurant_id?: number | "";
  date_from?: string;
  date_to?: string;
  loss_category?: RecoveryLossCategory | "";
  include_ignored?: boolean;
  case_type?: RecoveryCaseType | "";
  recovery_stage?: RecoveryStage | "";
  min_amount?: string;
  max_amount?: string;
  needs_evidence?: boolean;
  limit?: number;
  offset?: number;
};

export type RecoveryTotals = {
  detected_amount: MoneyValue;
  claimable_amount: MoneyValue;
  missing_evidence_amount: MoneyValue;
  sent_amount: MoneyValue;
  recovered_amount: MoneyValue;
  refused_amount: MoneyValue;
  pending_amount: MoneyValue;
  detected_count: number;
  claimable_count: number;
  missing_evidence_count: number;
  sent_count: number;
  recovered_count: number;
  refused_count: number;
  manual_review_count: number;
  active_appeals_count: number;
  appeal_needed_count: number;
  escalations_needed_count: number;
  refused_under_appeal_amount: MoneyValue;
  manually_closed_amount: MoneyValue;
  recovery_rate: MoneyValue;
  review_coverage_rate: MoneyValue;
};

export type RecoveryBreakdownItem = {
  key: string;
  count: number;
  detected_amount: MoneyValue;
  claimable_amount: MoneyValue;
  recovered_amount: MoneyValue;
  refused_amount: MoneyValue;
  restaurant_id?: number;
  restaurant_name?: string;
};

export type RecoveryCase = {
  case_type: RecoveryCaseType;
  case_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string | null;
  customer_name: string | null;
  loss_category: RecoveryLossCategory;
  recovery_stage: RecoveryStage;
  detected_amount: MoneyValue;
  claimable_amount: MoneyValue;
  recovered_amount: MoneyValue;
  status: string;
  evidence_status: string | null;
  next_action: string | null;
  created_at: string;
  link_url: string;
};

export type RecoverySummary = {
  filters: {
    restaurant_id: number | null;
    date_from: string | null;
    date_to: string | null;
    loss_category: string | null;
    include_ignored: boolean;
  };
  totals: RecoveryTotals;
  by_restaurant: RecoveryBreakdownItem[];
  by_loss_category: RecoveryBreakdownItem[];
  by_recovery_stage: RecoveryBreakdownItem[];
  top_recoverable_cases: RecoveryCase[];
};

export type RecoveryCasesResponse = {
  cases: RecoveryCase[];
  limit: number;
  offset: number;
};

export type RecoveryAction = {
  action_type: RecoveryActionType;
  case_type: string;
  case_id: number;
  restaurant_name: string;
  priority: string;
  amount: MoneyValue;
  due_at: string | null;
  label: string;
  url: string;
};

export type RecoveryActionsResponse = {
  actions: RecoveryAction[];
  limit: number;
  offset: number;
};

export type WorkspaceAction = {
  title: string;
  description: string;
  restaurant: string | null;
  amount: MoneyValue;
  priority: string;
  action_url: string;
  action_type: WorkspaceActionType;
};

export type WorkspaceNextActionsResponse = {
  urgent: WorkspaceAction[];
  today: WorkspaceAction[];
  this_week: WorkspaceAction[];
  blocked: WorkspaceAction[];
  high_value: WorkspaceAction[];
};

export type WorkspaceUnclassifiedItem = {
  source_type: string;
  source_id: number;
  original_filename: string;
  title: string;
  description: string;
  restaurant: string | null;
  reason: string;
  missing_fields: string[];
  action_url: string;
  created_at: string;
};

export type WorkspaceUnclassifiedResponse = {
  items: WorkspaceUnclassifiedItem[];
  total_count: number;
};

export type WorkspaceMachineTrigger = "manual" | "smart_import" | "refunds" | "cancellations";

export type WorkspaceMachineRunPayload = {
  trigger?: WorkspaceMachineTrigger;
  restaurant_id?: number | null;
  smart_import_batch_id?: number | null;
  sync_gmail?: boolean;
  run_autopilot?: boolean;
  run_historical_cleanup?: boolean;
};

export type WorkspaceMachineStage = {
  name: string;
  status: "completed" | "skipped" | "warning" | "failed";
  processed_count: number;
  created_count: number;
  sent_count: number;
  skipped_count: number;
  failed_count: number;
  warnings: string[];
  errors: string[];
};

export type WorkspaceMachineRunResponse = {
  status: "completed" | "warning" | "failed";
  trigger: WorkspaceMachineTrigger;
  recipient_email: string;
  stages: WorkspaceMachineStage[];
  next_actions: WorkspaceNextActionsResponse;
};

export type RecoveryMachineRailKey = "refunds" | "cancellations";
export type RecoveryMachineStageKey =
  | "smart_import"
  | "evidence_needed"
  | "evidence_received"
  | "uber_emails"
  | "followups"
  | "payments";
export type RecoveryMachineStageStatus = "empty" | "ready" | "attention" | "working" | "done";

export type RecoveryMachineStage = {
  key: RecoveryMachineStageKey;
  label: string;
  description: string;
  count: number;
  amount: MoneyValue;
  status: RecoveryMachineStageStatus;
  href: string;
};

export type RecoveryMachineRail = {
  key: RecoveryMachineRailKey;
  title: string;
  short_title: string;
  description: string;
  href: string;
  primary_action_label: string;
  primary_action_href: string;
  detected_count: number;
  detected_amount: MoneyValue;
  claimable_amount: MoneyValue;
  missing_evidence_count: number;
  evidence_ready_count: number;
  email_pipeline_count: number;
  followup_or_appeal_count: number;
  recovered_count: number;
  recovered_amount: MoneyValue;
  progress_percent: number;
  health: "empty" | "good" | "attention" | "working";
  next_action_label: string;
  next_action_href: string;
  stages: RecoveryMachineStage[];
};

export type RecoveryMachineResponse = {
  title: string;
  subtitle: string;
  global_progress_percent: number;
  total_detected_amount: MoneyValue;
  total_recovered_amount: MoneyValue;
  total_actions_count: number;
  rails: RecoveryMachineRail[];
};

export type SmartImportFilePreview = {
  id: number;
  original_filename: string;
  file_type: string;
  detected_category: SmartImportCategory;
  detected_report_type: UberReportingReportType | null;
  detected_evidence_type: string | null;
  detected_restaurant_name: string | null;
  detected_date_from: string | null;
  detected_date_to: string | null;
  header_row_number: number | null;
  skipped_preamble_rows: number;
  confidence: MoneyValue;
  recommended_action: SmartImportRecommendedAction;
  status: "previewed" | "confirmed" | "routed" | "ignored" | "failed" | "expired" | "manual_review";
  destination_type: string | null;
  destination_id: number | null;
  destination_url: string | null;
  error_message: string | null;
  warnings: string[];
  detected_columns: string[];
  metadata_json: Record<string, unknown> | null;
};

export type SmartImportFileDecision = {
  file_id: number;
  action?: SmartImportRecommendedAction | null;
  report_type?: UberReportingReportType | null;
  restaurant_id?: number | null;
};

export type SmartImportRoutedFile = {
  file_id: number;
  original_filename: string;
  action: SmartImportRecommendedAction;
  destination_type: string | null;
  destination_id: number | null;
  destination_url: string | null;
  processing_status: string | null;
  created_snapshots_count: number | null;
  created_transactions_count: number | null;
  analyzed_files_count: number | null;
  auto_matched_count: number | null;
  needs_review_count: number | null;
  skipped_rows: number | null;
  processing_errors: string[];
};

export type SmartImportPreviewResponse = {
  batch_preview_id: number;
  status: string;
  files: SmartImportFilePreview[];
};

export type SmartImportConfirmResponse = {
  batch_preview_id: number;
  status: string;
  routed_files: SmartImportRoutedFile[];
  manual_review_files: SmartImportRoutedFile[];
  ignored_files: SmartImportRoutedFile[];
  errors: Array<{ file_id: number; original_filename: string; error: string }>;
};

export type EvidenceImportBatch = {
  id: number;
  uploaded_by_user_id: number;
  restaurant_id: number | null;
  original_filename: string | null;
  source_type: EvidenceImportSourceType;
  status: EvidenceImportBatchStatus;
  total_files: number;
  stored_files_count: number;
  analyzed_files_count: number;
  auto_matched_count: number;
  needs_review_count: number;
  failed_files_count: number;
  duplicate_files_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type EvidenceImportedFile = {
  id: number;
  batch_id: number;
  uploaded_by_user_id: number;
  original_filename: string;
  internal_filename: string;
  storage_backend: string;
  mime_type: string | null;
  file_size: number;
  checksum_sha256: string;
  page_count: number | null;
  image_width: number | null;
  image_height: number | null;
  status: EvidenceImportedFileStatus;
  created_at: string;
  updated_at: string;
  preview_url: string;
};

export type EvidenceAnalysisResult = {
  id: number;
  imported_file_id: number;
  provider: EvidenceAnalysisProvider;
  model_name: string | null;
  status: EvidenceAnalysisStatus;
  extracted_text: string | null;
  detected_evidence_type: EvidenceAnalysisType;
  detected_restaurant_name: string | null;
  detected_uber_order_number: string | null;
  detected_display_id: string | null;
  detected_order_date: string | null;
  detected_order_amount: MoneyValue;
  detected_currency: string | null;
  detected_keywords_json: string[] | null;
  classification_confidence: MoneyValue;
  extraction_confidence: MoneyValue;
  matching_confidence: MoneyValue;
  raw_result_json: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type EvidenceMatchCandidate = {
  id: number;
  imported_file_id: number;
  analysis_result_id: number;
  candidate_type: EvidenceMatchCandidateType;
  candidate_id: number;
  restaurant_id: number | null;
  match_reason: string;
  match_score: MoneyValue;
  status: EvidenceMatchStatus;
  created_at: string;
  updated_at: string;
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
};

export type EvidenceImportedFileDetail = {
  file: EvidenceImportedFile;
  analysis_results: EvidenceAnalysisResult[];
  candidates: EvidenceMatchCandidate[];
};

export type EvidenceImportsResponse = {
  batches: EvidenceImportBatch[];
  limit: number;
  offset: number;
};

export type EvidenceImportFilesResponse = {
  files: EvidenceImportedFile[];
  limit: number;
  offset: number;
};

export type EvidenceImportAnalyzeResponse = {
  batch_id: number;
  status: EvidenceImportBatchStatus;
  analyzed_files_count: number;
  auto_matched_count: number;
  needs_review_count: number;
  failed_files_count: number;
  errors: string[];
};

export type EvidenceAttachResponse = {
  decision: {
    id: number;
    imported_file_id: number;
    evidence_file_id: number | null;
    candidate_type: EvidenceMatchCandidateType;
    candidate_id: number;
    decision: EvidenceAttachmentDecisionType;
    decided_by_user_id: number;
    reason: string | null;
    created_at: string;
  };
  evidence_file: EvidenceFile | null;
  validation: ClaimValidationResponse | null;
};

export type EvidenceBulkAcceptResponse = {
  accepted_count: number;
  skipped_count: number;
  errors: string[];
};

export type AppealWorkflow = {
  id: number;
  case_type: AppealCaseType;
  case_id: number;
  restaurant_id: number;
  claim_order_id: number | null;
  customer_refund_dispute_id: number | null;
  reconciliation_result_id: number | null;
  status: AppealWorkflowStatus;
  current_level: number;
  refusal_count: number;
  appeal_attempt_count: number;
  last_refusal_at: string | null;
  last_appeal_sent_at: string | null;
  next_action_at: string | null;
  next_action_type: AppealNextActionType | null;
  opened_by_user_id: number | null;
  manually_closed_by_user_id: number | null;
  manually_closed_at: string | null;
  manual_close_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type AppealAttempt = {
  id: number;
  workflow_id: number;
  attempt_number: number;
  appeal_type: AppealType;
  status: AppealAttemptStatus;
  based_on_refusal_message_id: number | null;
  email_draft_id: number | null;
  provider_draft_id: number | null;
  sent_email_thread_id: number | null;
  argument_summary: string | null;
  new_evidence_summary: string | null;
  created_by_user_id: number | null;
  sent_by_user_id: number | null;
  created_at: string;
  sent_at: string | null;
  completed_at: string | null;
};

export type RefusalAnalysis = {
  id: number;
  workflow_id: number;
  inbound_message_id: number | null;
  review_id: number | null;
  refusal_source: string;
  refusal_reason: string;
  refusal_text_excerpt: string | null;
  recommended_next_action: string;
  required_evidence_types_json: string[] | null;
  confidence: MoneyValue;
  created_at: string;
};

export type AppealWorkflowSummary = {
  id: number;
  case_type: AppealCaseType;
  case_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string | null;
  amount: MoneyValue;
  currency: string;
  status: AppealWorkflowStatus;
  next_action_type: AppealNextActionType | null;
  next_action_at: string | null;
  refusal_count: number;
  appeal_attempt_count: number;
  created_at: string;
  updated_at: string;
};

export type AppealsResponse = {
  workflows: AppealWorkflowSummary[];
  limit: number;
  offset: number;
};

export type AppealDetailResponse = {
  workflow: AppealWorkflow;
  case_summary: Record<string, unknown>;
  attempts: AppealAttempt[];
  refusal_analyses: RefusalAnalysis[];
  evidence_tasks: EvidenceRequestTaskSummary[];
  email_history: EmailDraft[];
};

export type AppealRecalculateResponse = {
  created_workflows: number;
  existing_workflows: number;
  errors: string[];
};

export type UberStatus = {
  provider: "uber_eats";
  status: UberIntegrationStatus;
  official_api_enabled: boolean;
  approval_required: boolean;
  scopes: string | null;
  store_mappings_count: number;
};

export type UberStoreMapping = {
  id: number;
  restaurant_id: number;
  uber_store_id: string;
  uber_store_name: string;
  merchant_store_id: string | null;
  external_reference_id: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type UberStoreMappingCreatePayload = {
  restaurant_id: number;
  uber_store_id?: string | null;
  uber_store_name: string;
  merchant_store_id?: string | null;
  external_reference_id?: string | null;
  active: boolean;
};

export type UberReportingImportResponse = {
  snapshots_created: number;
  transactions_created: number;
  rows_skipped: number;
  errors: string[];
};

export type UberReportingImportRow = {
  id: number;
  batch_id: number;
  row_number: number;
  raw_data: Record<string, unknown>;
  normalized_data: Record<string, unknown> | null;
  status: UberReportingRowStatus;
  errors: string[];
  warnings: string[];
  created_snapshot_id: number | null;
  created_transaction_id: number | null;
  created_at: string;
};

export type UberReportingImportBatch = {
  id: number;
  uploaded_by_user_id: number;
  original_filename: string;
  report_type: UberReportingReportType;
  file_type: string;
  status: UberReportingBatchStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  warning_rows: number;
  created_snapshots_count: number;
  created_transactions_count: number;
  duplicate_rows: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
};

export type UberReportingPreviewResponse = UberReportingImportBatch & {
  batch_id: number;
  unmapped_store_ids: string[];
  detected_columns: string[];
  rows_preview: UberReportingImportRow[];
};

export type UberReportingRowsResponse = {
  rows: UberReportingImportRow[];
  limit: number;
  offset: number;
};

export type UberReportingConfirmResponse = {
  batch_id: number;
  status: UberReportingBatchStatus;
  created_snapshots_count: number;
  created_transactions_count: number;
  skipped_rows: number;
  errors: string[];
};

export type UberUnmappedStore = {
  uber_store_id: string;
  uber_store_name: string | null;
  row_count: number;
  suggested_restaurant_matches: Restaurant[];
};

export type UberReconciliationRunPayload = {
  restaurant_id?: number | null;
  date_from?: string | null;
  date_to?: string | null;
  dry_run?: boolean;
};

export type UberReconciliationRun = {
  id: number;
  created_by_user_id: number;
  restaurant_id: number | null;
  date_from: string;
  date_to: string;
  status: UberReconciliationRunStatus;
  total_orders_analyzed: number;
  canceled_orders_count: number;
  compensated_count: number;
  not_compensated_count: number;
  partially_compensated_count: number;
  already_claimed_count: number;
  needs_evidence_count: number;
  manual_review_count: number;
  total_claimable_amount: MoneyValue;
  total_missing_amount: MoneyValue;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type UberReconciliationRunResponse = {
  run_id: number;
  status: UberReconciliationRunStatus;
  total_orders_analyzed: number;
  canceled_orders_count: number;
  compensated_count: number;
  not_compensated_count: number;
  partially_compensated_count: number;
  already_claimed_count: number;
  needs_evidence_count: number;
  manual_review_count: number;
  total_claimable_amount: MoneyValue;
  total_missing_amount: MoneyValue;
  errors: string[];
};

export type UberReconciliationResult = {
  id: number;
  run_id: number | null;
  restaurant_id: number;
  uber_order_id: string;
  display_id: string | null;
  claim_order_id: number | null;
  status: UberReconciliationStatus;
  financial_status: UberReconciliationFinancialStatus | null;
  reason: string;
  order_amount: MoneyValue;
  paid_amount: MoneyValue;
  refunded_amount: MoneyValue;
  missing_amount: MoneyValue;
  currency: string;
  evidence_required: boolean;
  confidence_score: MoneyValue;
  matched_transaction_ids_json: number[] | null;
  matched_snapshot_id: number | null;
  created_at: string;
  updated_at: string;
};

export type UberReconciliationResultsResponse = {
  results: UberReconciliationResult[];
  limit: number;
  offset: number;
};

export type UberReconciliationResultDetail = {
  result: UberReconciliationResult;
  snapshot: Record<string, unknown> | null;
  transactions: Record<string, unknown>[];
  claim_order: ClaimOrder | null;
};

export type UberReconciliationBulkCreateResponse = {
  created_count: number;
  skipped_count: number;
  errors: string[];
  created_order_ids: number[];
};

export type ImportRow = {
  id: number;
  batch_id: number;
  row_number: number;
  raw_data: Record<string, unknown>;
  normalized_data: Record<string, unknown> | null;
  status: ImportRowStatus;
  errors: string[];
  warnings: string[];
  created_order_id: number | null;
  created_at: string;
};

export type ImportBatch = {
  id: number;
  batch_id: number;
  uploaded_by_user_id: number;
  original_filename: string;
  file_type: string;
  status: ImportBatchStatus;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  unauthorized_rows: number;
  created_orders_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
};

export type ImportPreviewResponse = ImportBatch & {
  rows_preview: ImportRow[];
};

export type ImportRowsResponse = {
  rows: ImportRow[];
  limit: number;
  offset: number;
};

export type ImportConfirmResponse = {
  batch_id: number;
  status: ImportBatchStatus;
  created_orders_count: number;
  skipped_rows: number;
  errors: string[];
};

export type User = {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  active: boolean;
  created_at: string;
  updated_at: string;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: User;
};

export type LoginPayload = {
  email: string;
  password: string;
};

export type RegisterOwnerPayload = {
  email: string;
  password: string;
  full_name?: string | null;
};

export type UserCreatePayload = {
  email: string;
  password: string;
  full_name?: string | null;
  role: UserRole;
  active: boolean;
};

export type UserUpdatePayload = {
  email?: string;
  password?: string;
  full_name?: string | null;
  role?: UserRole;
  active?: boolean;
};

export type UserRestaurantAccess = {
  id: number;
  user_id: number;
  restaurant_id: number;
  created_at: string;
};

export type ClaimValidationResponse = {
  order_id: number;
  is_complete: boolean;
  previous_status: ClaimOrderStatus | null;
  new_status: ClaimOrderStatus | null;
  missing_items: string[];
  blocking_reasons: string[];
};

export type RestaurantCreatePayload = {
  name: string;
  legal_name?: string | null;
  address?: string | null;
  phone_number?: string | null;
  sender_email: string;
  uber_merchant_id?: string | null;
  active: boolean;
  autopilot_enabled?: boolean;
};

export type RestaurantUpdatePayload = Partial<RestaurantCreatePayload>;

export type AutopilotSettings = {
  enabled: boolean;
  initial_claims_enabled: boolean;
  followups_enabled: boolean;
  appeals_enabled: boolean;
  daily_send_limit: number;
  per_restaurant_daily_limit: number;
  min_amount: MoneyValue;
  max_amount_without_owner_review: MoneyValue;
  require_complete_evidence: boolean;
  require_gmail_connected: boolean;
  cooldown_hours: number;
  refusal_retry_enabled: boolean;
  max_appeal_attempts: number;
  never_close_on_refusal: boolean;
};

export type AutopilotStatusResponse = {
  settings: AutopilotSettings;
  gmail_provider_enabled: boolean;
  gmail_connected: boolean;
  gmail_email_address: string | null;
  emergency_stopped: boolean;
  sent_today_count: number;
  remaining_today_count: number;
};

export type AutopilotRunPayload = {
  mode: Exclude<AutopilotMode, "emergency_stop">;
  restaurant_id?: number | null;
  dry_run?: boolean;
};

export type AutopilotRun = {
  id: number;
  started_by_user_id: number | null;
  status: AutopilotRunStatus;
  mode: AutopilotMode;
  total_candidates: number;
  sent_count: number;
  skipped_count: number;
  failed_count: number;
  created_at: string;
  completed_at: string | null;
  error_message: string | null;
};

export type AutopilotAction = {
  id: number;
  run_id: number;
  case_type: AutopilotCaseType;
  case_id: number;
  restaurant_id: number;
  action_type: AutopilotActionType;
  status: AutopilotActionStatus;
  reason: string;
  email_draft_id: number | null;
  provider_draft_id: number | null;
  sent_at: string | null;
  skipped_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type AutopilotRunDetail = {
  run: AutopilotRun;
  actions: AutopilotAction[];
};

export type AutopilotRunsResponse = {
  runs: AutopilotRun[];
  limit: number;
  offset: number;
};

export type AutopilotActionsResponse = {
  actions: AutopilotAction[];
  limit: number;
  offset: number;
};

export type ClaimOrderCreatePayload = {
  restaurant_id: number;
  internal_reference?: string | null;
  uber_order_number: string;
  customer_name?: string | null;
  order_date?: string | null;
  order_time?: string | null;
  cancellation_time?: string | null;
  order_amount: string;
  currency: string;
  accepted_by_restaurant?: boolean | null;
  prepared_before_cancellation?: boolean | null;
  loss_type?: string | null;
  notes?: string | null;
};

export type EvidenceCreatePayload = {
  evidence_type: EvidenceType;
  original_filename: string;
  storage_path: string;
  mime_type?: string | null;
  file_size?: number | null;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(status === 401 ? SESSION_EXPIRED_MESSAGE : formatApiError(detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function getStoredRefreshToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
}

export function setStoredRefreshToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  window.localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function consumeSessionExpiredMessage(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const message = window.sessionStorage.getItem(SESSION_EXPIRED_STORAGE_KEY);
  window.sessionStorage.removeItem(SESSION_EXPIRED_STORAGE_KEY);
  return message;
}

function handleUnauthorizedResponse(): void {
  if (typeof window === "undefined") {
    return;
  }

  clearStoredToken();
  window.sessionStorage.setItem(SESSION_EXPIRED_STORAGE_KEY, SESSION_EXPIRED_MESSAGE);
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));

  if (window.location.pathname !== "/login") {
    window.location.replace("/login");
  }
}

function shouldHandleUnauthorized(path: string): boolean {
  return !path.startsWith("/v1/auth/login") && !path.startsWith("/v1/auth/register") && !path.startsWith("/v1/auth/refresh");
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken();
  if (!refreshToken) {
    return null;
  }
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE_URL}/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          return null;
        }
        const payload = (await response.json()) as TokenResponse;
        setStoredToken(payload.access_token);
        setStoredRefreshToken(payload.refresh_token);
        return payload.access_token;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

async function request<T>(path: string, init: RequestInit = {}, retryOnUnauthorized = true): Promise<T> {
  const token = getStoredToken();
  const isFormData = init.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    if (response.status === 401 && shouldHandleUnauthorized(path)) {
      if (retryOnUnauthorized) {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken) {
          return request<T>(path, init, false);
        }
      }
      handleUnauthorizedResponse();
    }
    throw new ApiError(response.status, payload);
  }

  return payload as T;
}

async function publicRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isFormData = init.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    throw new ApiError(response.status, payload);
  }

  return payload as T;
}

function formatApiError(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => formatApiError(item)).join(", ");
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") {
      return record.message;
    }
    if (typeof record.detail === "string") {
      return record.detail;
    }
    if (Array.isArray(record.detail)) {
      return record.detail.map((item) => formatApiError(item)).join(", ");
    }
    return JSON.stringify(detail);
  }
  return "Erreur API";
}

function postJson<TResponse, TPayload>(path: string, payload: TPayload): Promise<TResponse> {
  return request<TResponse>(path, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

function buildQuery(filters: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function downloadBlob(path: string, retryOnUnauthorized = true): Promise<Blob> {
  const token = getStoredToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
  });
  const contentType = response.headers.get("content-type") ?? "";
  if (!response.ok) {
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (response.status === 401 && shouldHandleUnauthorized(path)) {
      if (retryOnUnauthorized) {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken) {
          return downloadBlob(path, false);
        }
      }
      handleUnauthorizedResponse();
    }
    throw new ApiError(response.status, payload);
  }
  return response.blob();
}

export const api = {
  login: async (payload: LoginPayload) => {
    const response = await postJson<TokenResponse, LoginPayload>("/v1/auth/login", payload);
    setStoredToken(response.access_token);
    setStoredRefreshToken(response.refresh_token);
    return response;
  },
  registerOwner: async (payload: RegisterOwnerPayload) => {
    const response = await postJson<TokenResponse, RegisterOwnerPayload>("/v1/auth/register", payload);
    setStoredToken(response.access_token);
    setStoredRefreshToken(response.refresh_token);
    return response;
  },
  getMe: () => request<User>("/v1/auth/me"),
  logout: () => clearStoredToken(),
  getDashboardSummary: () => request<DashboardSummary>("/v1/dashboard/summary"),
  getCommercialSummary: (filters: ReportFilters = {}) =>
    request<CommercialSummary>(`/v1/reports/commercial-summary${buildQuery(filters)}`),
  getReportOrders: (filters: ReportFilters = {}) => request<ReportOrdersResponse>(`/v1/reports/orders${buildQuery(filters)}`),
  getReportFollowups: (filters: ReportFilters = {}) =>
    request<ReportFollowupsResponse>(`/v1/reports/followups${buildQuery(filters)}`),
  getReportResponses: (filters: ReportFilters = {}) =>
    request<ReportResponsesResponse>(`/v1/reports/responses${buildQuery(filters)}`),
  downloadReport: (path: string, filters: ReportFilters = {}) => downloadBlob(`${path}${buildQuery(filters)}`),
  getRestaurants: (filters: { include_inactive?: boolean } = {}) =>
    request<Restaurant[]>(`/v1/restaurants${buildQuery(filters)}`),
  getRestaurant: (id: number) => request<Restaurant>(`/v1/restaurants/${id}`),
  createRestaurant: (payload: RestaurantCreatePayload) =>
    postJson<Restaurant, RestaurantCreatePayload>("/v1/restaurants", payload),
  updateRestaurant: (id: number, payload: RestaurantUpdatePayload) =>
    request<Restaurant>(`/v1/restaurants/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  archiveRestaurant: (id: number) =>
    request<Restaurant>(`/v1/restaurants/${id}`, {
      method: "DELETE",
    }),
  restoreRestaurant: (id: number) => postJson<Restaurant, Record<string, never>>(`/v1/restaurants/${id}/restore`, {}),
  getUsers: () => request<User[]>("/v1/users"),
  createUser: (payload: UserCreatePayload) => postJson<User, UserCreatePayload>("/v1/users", payload),
  getUser: (id: number) => request<User>(`/v1/users/${id}`),
  updateUser: (id: number, payload: UserUpdatePayload) =>
    request<User>(`/v1/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  assignUserRestaurant: (id: number, restaurantId: number) =>
    postJson<UserRestaurantAccess, { restaurant_id: number }>(`/v1/users/${id}/restaurants`, {
      restaurant_id: restaurantId,
    }),
  removeUserRestaurant: (id: number, restaurantId: number) =>
    request<void>(`/v1/users/${id}/restaurants/${restaurantId}`, {
      method: "DELETE",
    }),
  getOrders: () => request<ClaimOrder[]>("/v1/orders"),
  createOrder: (payload: ClaimOrderCreatePayload) =>
    postJson<ClaimOrder, ClaimOrderCreatePayload>("/v1/orders", payload),
  getOrder: (id: number) => request<ClaimOrder>(`/v1/orders/${id}`),
  updateOrder: (id: number, payload: Partial<ClaimOrderCreatePayload>) =>
    request<ClaimOrder>(`/v1/orders/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getEvidence: (id: number) => request<EvidenceFile[]>(`/v1/orders/${id}/evidence`),
  createEvidence: (id: number, payload: EvidenceCreatePayload) =>
    postJson<EvidenceFile, EvidenceCreatePayload>(`/v1/orders/${id}/evidence`, payload),
  uploadEvidence: (id: number, evidenceType: EvidenceType, file: File) => {
    const formData = new FormData();
    formData.append("evidence_type", evidenceType);
    formData.append("file", file);
    return request<EvidenceFile>(`/v1/orders/${id}/evidence/upload`, {
      method: "POST",
      body: formData,
    });
  },
  downloadEvidence: async (id: number) => {
    const token = getStoredToken();
    const response = await fetch(`${API_BASE_URL}/v1/evidence/${id}/download`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      cache: "no-store",
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!response.ok) {
      const payload = contentType.includes("application/json") ? await response.json() : await response.text();
      if (response.status === 401) {
        handleUnauthorizedResponse();
      }
      throw new ApiError(response.status, payload);
    }
    return response.blob();
  },
  validateOrder: (id: number) =>
    postJson<ClaimValidationResponse, Record<string, never>>(`/v1/orders/${id}/validate`, {}),
  createOrderDraft: (id: number, draftType: EmailDraftType) =>
    postJson<EmailDraft, { draft_type: EmailDraftType }>(`/v1/orders/${id}/drafts`, {
      draft_type: draftType,
    }),
  getOrderDrafts: (id: number) => request<EmailDraft[]>(`/v1/orders/${id}/drafts`),
  getDrafts: () => request<EmailDraftSummary[]>("/v1/drafts"),
  getGmailStatus: () => request<GmailConnectionStatus>("/v1/email/gmail/status"),
  getResendStatus: () => request<GmailConnectionStatus>("/v1/email/resend/status"),
  getGmailAccounts: () => request<EmailAccount[]>("/v1/email/gmail/accounts"),
  getGmailRestaurantMappings: () => request<GmailRestaurantMapping[]>("/v1/email/gmail/restaurant-mappings"),
  updateGmailRestaurantMapping: (restaurantId: number, emailAccountId: number | null) =>
    request<GmailRestaurantMapping>(`/v1/email/gmail/restaurant-mappings/${restaurantId}`, {
      method: "PUT",
      body: JSON.stringify({ email_account_id: emailAccountId }),
    }),
  startGmailOAuth: () => request<GmailOAuthStartResponse>("/v1/email/gmail/oauth/start"),
  disconnectGmail: () =>
    request<{ disconnected: boolean }>("/v1/email/gmail/disconnect", {
      method: "POST",
    }),
  createGmailDraft: (draftId: number, payload: GmailDraftCreatePayload) =>
    postJson<EmailProviderDraft, GmailDraftCreatePayload>(`/v1/drafts/${draftId}/gmail-draft`, payload),
  sendGmailProviderDraft: (providerDraftId: string, payload: GmailDraftSendPayload) =>
    postJson<GmailDraftSendResponse, GmailDraftSendPayload>(
      `/v1/email/gmail/provider-drafts/${encodeURIComponent(providerDraftId)}/send`,
      payload,
    ),
  sendResendDraft: (draftId: number, payload: ResendSendPayload) =>
    postJson<EmailProviderDraft, ResendSendPayload>(`/v1/drafts/${draftId}/resend-send`, payload),
  getInboundStatus: () => request<GmailInboundStatus>("/v1/email/gmail/inbound/status"),
  getGmailRelanceDashboard: (limit = 80, refresh = false) =>
    request<GmailRelanceDashboard>(
      `/v1/email/gmail/relances?limit=${encodeURIComponent(String(limit))}&refresh=${refresh ? "true" : "false"}`,
    ),
  syncInboundGmail: (payload: GmailInboundSyncPayload = {}) =>
    postJson<GmailInboundSyncResponse, GmailInboundSyncPayload>("/v1/email/gmail/inbound/sync", payload),
  analyzeInboundGmail: (payload: GmailResponseAnalyzePayload = {}) =>
    postJson<GmailResponseAnalyzeResponse, GmailResponseAnalyzePayload>("/v1/email/gmail/inbound/analyze", payload),
  analyzeInboundMessage: (messageId: number, payload: GmailResponseAnalyzePayload = {}) =>
    postJson<GmailResponseAnalysis, GmailResponseAnalyzePayload>(
      `/v1/email/inbound-messages/${messageId}/analyze`,
      payload,
    ),
  getInboundMessages: (filters: { match_status?: InboundEmailMatchStatus | ""; order_id?: number; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.match_status) {
      params.set("match_status", filters.match_status);
    }
    if (filters.order_id) {
      params.set("order_id", String(filters.order_id));
    }
    if (filters.limit) {
      params.set("limit", String(filters.limit));
    }
    if (filters.offset) {
      params.set("offset", String(filters.offset));
    }
    const query = params.toString();
    return request<InboundMessagesResponse>(`/v1/email/inbound-messages${query ? `?${query}` : ""}`);
  },
  getOrderEmailMessages: (orderId: number) => request<OrderEmailMessagesResponse>(`/v1/orders/${orderId}/email-messages`),
  linkInboundMessage: (messageId: number, orderId: number) =>
    postJson<InboundEmailMessage, { order_id: number }>(`/v1/email/inbound-messages/${messageId}/link`, {
      order_id: orderId,
    }),
  createResponseReview: (orderId: number, payload: ClaimResponseReviewCreatePayload) =>
    postJson<ClaimResponseReview, ClaimResponseReviewCreatePayload>(
      `/v1/orders/${orderId}/response-reviews`,
      payload,
    ),
  getOrderResponseReviews: (orderId: number) =>
    request<ClaimResponseReview[]>(`/v1/orders/${orderId}/response-reviews`),
  getResponseReviews: (
    filters: {
      review_type?: ClaimResponseReviewType | "";
      restaurant_id?: number;
      order_id?: number;
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const params = new URLSearchParams();
    if (filters.review_type) {
      params.set("review_type", filters.review_type);
    }
    if (filters.restaurant_id) {
      params.set("restaurant_id", String(filters.restaurant_id));
    }
    if (filters.order_id) {
      params.set("order_id", String(filters.order_id));
    }
    if (filters.limit) {
      params.set("limit", String(filters.limit));
    }
    if (filters.offset) {
      params.set("offset", String(filters.offset));
    }
    const query = params.toString();
    return request<ResponseReviewsResponse>(`/v1/response-reviews${query ? `?${query}` : ""}`);
  },
  getDueFollowups: (
    filters: {
      restaurant_id?: number;
      status?: FollowUpTaskStatus | "";
      task_type?: FollowUpTaskType | "";
      limit?: number;
      offset?: number;
    } = {},
  ) => {
    const params = new URLSearchParams();
    if (filters.restaurant_id) {
      params.set("restaurant_id", String(filters.restaurant_id));
    }
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.task_type) {
      params.set("task_type", filters.task_type);
    }
    if (filters.limit) {
      params.set("limit", String(filters.limit));
    }
    if (filters.offset) {
      params.set("offset", String(filters.offset));
    }
    const query = params.toString();
    return request<FollowUpsResponse>(`/v1/followups/due${query ? `?${query}` : ""}`);
  },
  recalculateFollowups: (payload: FollowUpRecalculatePayload = {}) =>
    postJson<FollowUpRecalculateResponse, FollowUpRecalculatePayload>("/v1/followups/recalculate", payload),
  createFollowupDraft: (taskId: number) =>
    postJson<FollowUpTask, Record<string, never>>(`/v1/followups/${taskId}/create-draft`, {}),
  createFollowupGmailDraft: (taskId: number) =>
    postJson<FollowUpTask, Record<string, never>>(`/v1/followups/${taskId}/create-gmail-draft`, {}),
  skipFollowupTask: (taskId: number, payload: { skip_reason: string }) =>
    postJson<FollowUpTask, { skip_reason: string }>(`/v1/followups/${taskId}/skip`, payload),
  completeFollowupTask: (taskId: number) =>
    postJson<FollowUpTask, Record<string, never>>(`/v1/followups/${taskId}/complete`, {}),
  getEvidenceTasks: (
    filters: {
      restaurant_id?: number;
      status?: EvidenceRequestTaskStatus | "";
      required_evidence_type?: EvidenceType | "";
      priority?: EvidenceRequestPriority | "";
      assigned_to_me?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<EvidenceRequestTasksResponse>(`/v1/evidence-tasks${buildQuery(filters)}`),
  getLiveEvidenceStation: (
    filters: {
      restaurant_id?: number;
      status?: EvidenceRequestTaskStatus | "";
      priority?: EvidenceRequestPriority | "";
      assigned_to_me?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<LiveEvidenceStationResponse>(`/v1/live-evidence/station${buildQuery(filters)}`),
  getEvidenceTask: (taskId: number) => request<EvidenceRequestTask>(`/v1/evidence-tasks/${taskId}`),
  recalculateEvidenceTasks: (payload: EvidenceRequestRecalculatePayload = {}) =>
    postJson<EvidenceRequestRecalculateResponse, EvidenceRequestRecalculatePayload>(
      "/v1/evidence-tasks/recalculate",
      payload,
    ),
  uploadEvidenceTask: (taskId: number, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<EvidenceTaskUploadResponse>(`/v1/evidence-tasks/${taskId}/upload`, {
      method: "POST",
      body: formData,
    });
  },
  skipEvidenceTask: (taskId: number, payload: { skip_reason: string }) =>
    postJson<EvidenceRequestTask, { skip_reason: string }>(`/v1/evidence-tasks/${taskId}/skip`, payload),
  completeEvidenceTask: (taskId: number) =>
    postJson<EvidenceRequestTask, Record<string, never>>(`/v1/evidence-tasks/${taskId}/complete`, {}),
  createEvidenceUploadLink: (
    taskId: number,
    payload: { expires_in_hours?: number | null; max_uses?: number | null } = {},
  ) =>
    postJson<EvidenceUploadLinkCreateResponse, { expires_in_hours?: number | null; max_uses?: number | null }>(
      `/v1/evidence-tasks/${taskId}/upload-link`,
      payload,
    ),
  createEvidencePrintTicket: (
    taskId: number,
    payload: { expires_in_hours?: number | null; max_uses?: number | null } = {},
  ) =>
    postJson<EvidencePrintTicketResponse, { expires_in_hours?: number | null; max_uses?: number | null }>(
      `/v1/evidence-tasks/${taskId}/print-ticket`,
      payload,
    ),
  getPublicEvidenceUploadLink: (token: string) =>
    publicRequest<PublicEvidenceUploadLink>(`/v1/evidence-upload-links/${encodeURIComponent(token)}`),
  uploadPublicEvidenceLink: (token: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return publicRequest<EvidenceTaskUploadResponse>(`/v1/evidence-upload-links/${encodeURIComponent(token)}/upload`, {
      method: "POST",
      body: formData,
    });
  },
  revokeEvidenceUploadLink: (linkId: number) =>
    postJson<EvidenceUploadLink, Record<string, never>>(`/v1/evidence-upload-links/${linkId}/revoke`, {}),
  detectCustomerRefundDisputes: (payload: CustomerRefundDetectPayload = {}) =>
    postJson<CustomerRefundDetectResponse, CustomerRefundDetectPayload>("/v1/customer-refunds/detect", payload),
  getCustomerRefundDisputes: (
    filters: {
      restaurant_id?: number | "";
      dispute_type?: CustomerRefundDisputeType | "";
      status?: CustomerRefundDisputeStatus | "";
      evidence_status?: CustomerRefundEvidenceStatus | "";
      date_from?: string;
      date_to?: string;
      min_amount?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<CustomerRefundDisputesResponse>(`/v1/customer-refunds${buildQuery(filters)}`),
  getCustomerRefundDispute: (id: number) => request<CustomerRefundDisputeDetail>(`/v1/customer-refunds/${id}`),
  recalculateCustomerRefundEvidence: (id: number) =>
    postJson<UberCustomerRefundDispute, Record<string, never>>(`/v1/customer-refunds/${id}/recalculate-evidence`, {}),
  createClaimOrderFromCustomerRefund: (id: number) =>
    postJson<ClaimOrder, Record<string, never>>(`/v1/customer-refunds/${id}/create-claim-order`, {}),
  createCustomerRefundDraft: (id: number) =>
    postJson<EmailDraft, Record<string, never>>(`/v1/customer-refunds/${id}/create-draft`, {}),
  createCustomerRefundGmailDraft: (id: number) =>
    postJson<EmailProviderDraft, Record<string, never>>(`/v1/customer-refunds/${id}/create-gmail-draft`, {}),
  ignoreCustomerRefundDispute: (id: number, payload: { reason: string }) =>
    postJson<UberCustomerRefundDispute, { reason: string }>(`/v1/customer-refunds/${id}/ignore`, payload),
  createCustomerRefundReview: (id: number, payload: CustomerRefundDisputeReviewPayload) =>
    postJson<CustomerRefundDisputeReviewResponse, CustomerRefundDisputeReviewPayload>(
      `/v1/customer-refunds/${id}/reviews`,
      payload,
    ),
  getCustomerRefundReviews: (id: number) =>
    request<CustomerRefundDisputeReview[]>(`/v1/customer-refunds/${id}/reviews`),
  getCustomerRefundReviewsList: (
    filters: {
      restaurant_id?: number | "";
      review_type?: CustomerRefundReviewType | "";
      dispute_id?: number;
      date_from?: string;
      date_to?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<CustomerRefundDisputeReviewsResponse>(`/v1/customer-refund-reviews${buildQuery(filters)}`),
  bulkCreateCustomerRefundClaimOrders: (disputeIds: number[]) =>
    postJson<CustomerRefundBulkResponse, { dispute_ids: number[] }>("/v1/customer-refunds/bulk-create-claim-orders", {
      dispute_ids: disputeIds,
    }),
  bulkCreateCustomerRefundDrafts: (disputeIds: number[]) =>
    postJson<CustomerRefundBulkResponse, { dispute_ids: number[] }>("/v1/customer-refunds/bulk-create-drafts", {
      dispute_ids: disputeIds,
    }),
  getRecoverySummary: (filters: RecoveryFilters = {}) =>
    request<RecoverySummary>(`/v1/recovery/summary${buildQuery(filters)}`),
  getRecoveryCases: (filters: RecoveryFilters = {}) =>
    request<RecoveryCasesResponse>(`/v1/recovery/cases${buildQuery(filters)}`),
  getRecoveryActions: (filters: RecoveryFilters = {}) =>
    request<RecoveryActionsResponse>(`/v1/recovery/actions${buildQuery(filters)}`),
  getWorkspaceNextActions: () => request<WorkspaceNextActionsResponse>("/v1/workspace/next-actions"),
  getWorkspaceUnclassified: () => request<WorkspaceUnclassifiedResponse>("/v1/workspace/unclassified"),
  getWorkspaceRecoveryMachine: () => request<RecoveryMachineResponse>("/v1/workspace/recovery-machine"),
  runWorkspaceMachine: (payload: WorkspaceMachineRunPayload = {}) =>
    postJson<WorkspaceMachineRunResponse, WorkspaceMachineRunPayload>("/v1/workspace/machine/run", payload),
  previewSmartImport: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return request<SmartImportPreviewResponse>("/v1/smart-import/preview", {
      method: "POST",
      body: formData,
    });
  },
  getSmartImportPreview: (batchId: number) =>
    request<SmartImportPreviewResponse>(`/v1/smart-import/previews/${batchId}`),
  confirmSmartImport: (batchPreviewId: number, files: SmartImportFileDecision[] = []) =>
    postJson<SmartImportConfirmResponse, { batch_preview_id: number; files: SmartImportFileDecision[] }>("/v1/smart-import/confirm", {
      batch_preview_id: batchPreviewId,
      files,
    }),
  cancelSmartImport: (batchId: number) =>
    postJson<SmartImportPreviewResponse, Record<string, never>>(`/v1/smart-import/previews/${batchId}/cancel`, {}),
  downloadRecoverySummaryXlsx: (filters: RecoveryFilters = {}) =>
    downloadBlob(`/v1/recovery/export/summary.xlsx${buildQuery(filters)}`),
  downloadRecoveryCasesCsv: (filters: RecoveryFilters = {}) =>
    downloadBlob(`/v1/recovery/export/cases.csv${buildQuery(filters)}`),
  createEvidenceImport: (files: File[], restaurantId?: number | null) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    if (restaurantId) {
      formData.append("restaurant_id", String(restaurantId));
    }
    return request<EvidenceImportBatch>("/v1/evidence-imports", {
      method: "POST",
      body: formData,
    });
  },
  createEvidenceZipImport: (file: File, restaurantId?: number | null) => {
    const formData = new FormData();
    formData.append("file", file);
    if (restaurantId) {
      formData.append("restaurant_id", String(restaurantId));
    }
    return request<EvidenceImportBatch>("/v1/evidence-imports/zip", {
      method: "POST",
      body: formData,
    });
  },
  getEvidenceImports: (filters: { limit?: number; offset?: number } = {}) =>
    request<EvidenceImportsResponse>(`/v1/evidence-imports${buildQuery(filters)}`),
  getEvidenceImport: (batchId: number) => request<EvidenceImportBatch>(`/v1/evidence-imports/${batchId}`),
  getEvidenceImportFiles: (
    batchId: number,
    filters: {
      status?: EvidenceImportedFileStatus | "";
      detected_evidence_type?: EvidenceAnalysisType | "";
      needs_review?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<EvidenceImportFilesResponse>(`/v1/evidence-imports/${batchId}/files${buildQuery(filters)}`),
  analyzeEvidenceImport: (batchId: number, payload: { provider: EvidenceAnalysisProvider; limit?: number }) =>
    postJson<EvidenceImportAnalyzeResponse, { provider: EvidenceAnalysisProvider; limit?: number }>(
      `/v1/evidence-imports/${batchId}/analyze`,
      payload,
    ),
  bulkAcceptEvidenceImport: (batchId: number, payload: { min_score?: string | number } = {}) =>
    postJson<EvidenceBulkAcceptResponse, { min_score?: string | number }>(
      `/v1/evidence-imports/${batchId}/bulk-accept-high-confidence`,
      payload,
    ),
  getEvidenceImportedFile: (fileId: number) =>
    request<EvidenceImportedFileDetail>(`/v1/evidence-imported-files/${fileId}`),
  previewEvidenceImportedFile: (fileId: number) => downloadBlob(`/v1/evidence-imported-files/${fileId}/preview`),
  attachEvidenceImportedFile: (
    fileId: number,
    payload: { candidate_type: EvidenceMatchCandidateType; candidate_id: number; evidence_type: EvidenceType },
  ) =>
    postJson<EvidenceAttachResponse, { candidate_type: EvidenceMatchCandidateType; candidate_id: number; evidence_type: EvidenceType }>(
      `/v1/evidence-imported-files/${fileId}/attach`,
      payload,
    ),
  acceptEvidenceMatchCandidate: (candidateId: number) =>
    postJson<EvidenceAttachResponse, Record<string, never>>(`/v1/evidence-match-candidates/${candidateId}/accept`, {}),
  rejectEvidenceMatchCandidate: (candidateId: number, reason: string) =>
    postJson<EvidenceMatchCandidate, { reason: string }>(`/v1/evidence-match-candidates/${candidateId}/reject`, { reason }),
  ignoreEvidenceImportedFile: (fileId: number, reason: string) =>
    postJson<EvidenceAttachResponse["decision"], { reason: string }>(`/v1/evidence-imported-files/${fileId}/ignore`, {
      reason,
    }),
  getAppeals: (
    filters: {
      restaurant_id?: number | "";
      status?: AppealWorkflowStatus | "";
      case_type?: AppealCaseType | "";
      next_action_type?: AppealNextActionType | "";
      min_refusal_count?: number;
      limit?: number;
      offset?: number;
    } = {},
  ) => request<AppealsResponse>(`/v1/appeals${buildQuery(filters)}`),
  getAppeal: (workflowId: number) => request<AppealDetailResponse>(`/v1/appeals/${workflowId}`),
  recalculateAppeals: (payload: { restaurant_id?: number | null } = {}) =>
    postJson<AppealRecalculateResponse, { restaurant_id?: number | null }>("/v1/appeals/recalculate", payload),
  analyzeAppealRefusal: (workflowId: number) =>
    postJson<RefusalAnalysis, Record<string, never>>(`/v1/appeals/${workflowId}/analyze-refusal`, {}),
  createAppealDraft: (workflowId: number, payload: { appeal_type: AppealType }) =>
    postJson<AppealAttempt, { appeal_type: AppealType }>(`/v1/appeals/${workflowId}/create-draft`, payload),
  createAppealGmailDraft: (workflowId: number) =>
    postJson<AppealAttempt, Record<string, never>>(`/v1/appeals/${workflowId}/create-gmail-draft`, {}),
  markAppealSent: (workflowId: number) =>
    postJson<AppealAttempt, Record<string, never>>(`/v1/appeals/${workflowId}/mark-sent`, {}),
  pauseAppeal: (workflowId: number, payload: { reason: string }) =>
    postJson<AppealWorkflow, { reason: string }>(`/v1/appeals/${workflowId}/pause`, payload),
  manualCloseAppeal: (workflowId: number, payload: { reason: string }) =>
    postJson<AppealWorkflow, { reason: string }>(`/v1/appeals/${workflowId}/manual-close`, payload),
  reopenAppeal: (workflowId: number) =>
    postJson<AppealWorkflow, Record<string, never>>(`/v1/appeals/${workflowId}/reopen`, {}),
  getAutopilotStatus: () => request<AutopilotStatusResponse>("/v1/autopilot/status"),
  dryRunAutopilot: (payload: AutopilotRunPayload) =>
    postJson<AutopilotRunDetail, AutopilotRunPayload>("/v1/autopilot/dry-run", { ...payload, dry_run: true }),
  runAutopilot: (payload: AutopilotRunPayload) =>
    postJson<AutopilotRunDetail, AutopilotRunPayload>("/v1/autopilot/run", { ...payload, dry_run: false }),
  stopAutopilot: () => postJson<AutopilotRun, Record<string, never>>("/v1/autopilot/stop", {}),
  getAutopilotRuns: (filters: { limit?: number; offset?: number } = {}) =>
    request<AutopilotRunsResponse>(`/v1/autopilot/runs${buildQuery(filters)}`),
  getAutopilotRun: (id: number) => request<AutopilotRunDetail>(`/v1/autopilot/runs/${id}`),
  getAutopilotActions: (
    filters: {
      restaurant_id?: number | "";
      status?: AutopilotActionStatus | "";
      action_type?: AutopilotActionType | "";
      limit?: number;
      offset?: number;
    } = {},
  ) => request<AutopilotActionsResponse>(`/v1/autopilot/actions${buildQuery(filters)}`),
  getUberStatus: () => request<UberStatus>("/v1/uber/status"),
  getUberStoreMappings: () => request<UberStoreMapping[]>("/v1/uber/store-mappings"),
  createUberStoreMapping: (payload: UberStoreMappingCreatePayload) =>
    postJson<UberStoreMapping, UberStoreMappingCreatePayload>("/v1/uber/store-mappings", payload),
  updateUberStoreMapping: (id: number, payload: Partial<UberStoreMappingCreatePayload>) =>
    request<UberStoreMapping>(`/v1/uber/store-mappings/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  importUberReporting: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<UberReportingImportResponse>("/v1/uber/reporting/import", {
      method: "POST",
      body: formData,
    });
  },
  previewUberReportingImport: (file: File, reportType: UberReportingReportType) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<UberReportingPreviewResponse>(`/v1/uber/reporting/preview?report_type=${reportType}`, {
      method: "POST",
      body: formData,
    });
  },
  getUberReportingBatches: () => request<UberReportingImportBatch[]>("/v1/uber/reporting/batches"),
  getUberReportingBatch: (batchId: number) => request<UberReportingImportBatch>(`/v1/uber/reporting/batches/${batchId}`),
  getUberReportingRows: (batchId: number, filters: { status?: UberReportingRowStatus | ""; limit?: number; offset?: number } = {}) =>
    request<UberReportingRowsResponse>(`/v1/uber/reporting/batches/${batchId}/rows${buildQuery(filters)}`),
  confirmUberReportingBatch: (batchId: number) =>
    postJson<UberReportingConfirmResponse, Record<string, never>>(`/v1/uber/reporting/batches/${batchId}/confirm`, {}),
  cancelUberReportingBatch: (batchId: number) =>
    postJson<UberReportingImportBatch, Record<string, never>>(`/v1/uber/reporting/batches/${batchId}/cancel`, {}),
  getUberUnmappedStores: () => request<UberUnmappedStore[]>("/v1/uber/reporting/unmapped-stores"),
  mapUberUnmappedStore: (uberStoreId: string, restaurantId: number) =>
    postJson<UberStoreMapping, { restaurant_id: number }>(
      `/v1/uber/reporting/unmapped-stores/${encodeURIComponent(uberStoreId)}/map`,
      { restaurant_id: restaurantId },
    ),
  getUberReconciliationRuns: () => request<UberReconciliationRun[]>("/v1/uber/reconciliation/runs"),
  getUberReconciliationRun: (runId: number) => request<UberReconciliationRun>(`/v1/uber/reconciliation/runs/${runId}`),
  getUberReconciliationResults: (
    filters: {
      run_id?: number;
      restaurant_id?: number | "";
      status?: UberReconciliationStatus | "";
      date_from?: string;
      date_to?: string;
      min_missing_amount?: string;
      evidence_required?: boolean;
      limit?: number;
      offset?: number;
    } = {},
  ) =>
    request<UberReconciliationResultsResponse>(`/v1/uber/reconciliation/results${buildQuery(filters)}`),
  getUberReconciliationResult: (resultId: number) =>
    request<UberReconciliationResultDetail>(`/v1/uber/reconciliation/results/${resultId}`),
  runUberReconciliation: (payload: UberReconciliationRunPayload = {}) =>
    postJson<UberReconciliationRunResponse, UberReconciliationRunPayload>("/v1/uber/reconciliation/run", payload),
  createClaimOrderFromUberResult: (resultId: number) =>
    postJson<ClaimOrder, Record<string, never>>(`/v1/uber/reconciliation/results/${resultId}/claim-order`, {}),
  bulkCreateClaimOrdersFromUberResults: (resultIds: number[]) =>
    postJson<UberReconciliationBulkCreateResponse, { result_ids: number[] }>(
      "/v1/uber/reconciliation/results/bulk-create-claim-orders",
      { result_ids: resultIds },
    ),
  ignoreUberReconciliationResult: (resultId: number, reason: string) =>
    postJson<UberReconciliationResultsResponse, { reason: string }>(`/v1/uber/reconciliation/results/${resultId}/ignore`, {
      reason,
    }),
  previewOrderImport: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<ImportPreviewResponse>("/v1/imports/orders/preview", {
      method: "POST",
      body: formData,
    });
  },
  getImportBatches: () => request<ImportBatch[]>("/v1/imports"),
  getImportBatch: (id: number) => request<ImportBatch>(`/v1/imports/${id}`),
  getImportRows: (id: number, filters: { status?: ImportRowStatus | ""; limit?: number; offset?: number } = {}) => {
    const params = new URLSearchParams();
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.limit) {
      params.set("limit", String(filters.limit));
    }
    if (filters.offset) {
      params.set("offset", String(filters.offset));
    }
    const query = params.toString();
    return request<ImportRowsResponse>(`/v1/imports/${id}/rows${query ? `?${query}` : ""}`);
  },
  confirmImportBatch: (id: number) => postJson<ImportConfirmResponse, Record<string, never>>(`/v1/imports/${id}/confirm`, {}),
  cancelImportBatch: (id: number) => postJson<ImportBatch, Record<string, never>>(`/v1/imports/${id}/cancel`, {}),
};

export function formatCurrency(value: MoneyValue, currency = "EUR"): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  const numericValue = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(numericValue)) {
    return `${value} ${currency}`;
  }
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: currency || "EUR",
  }).format(numericValue);
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("fr-FR").format(new Date(value));
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

export function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
