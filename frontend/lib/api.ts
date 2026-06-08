const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_STORAGE_KEY = "ubereats_claims_manager_token";

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
  | "other";

export type EmailDraftType = "initial_claim" | "followup_1" | "followup_2" | "escalation" | "proof_reply";
export type ImportBatchStatus = "uploaded" | "parsed" | "confirmed" | "partially_imported" | "failed" | "cancelled";
export type ImportRowStatus = "valid" | "invalid" | "duplicate" | "unauthorized" | "created" | "skipped";
export type EmailProviderDraftStatus = "provider_draft_created" | "send_requested" | "sent" | "failed";
export type GmailSyncStatus = "idle" | "running" | "success" | "failed";
export type InboundEmailMatchStatus = "linked" | "unlinked" | "ignored";
export type InboundEmailReviewStatus = "unreviewed" | "reviewed" | "ignored";
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

export type Restaurant = {
  id: number;
  name: string;
  legal_name: string | null;
  address: string | null;
  sender_email: string;
  uber_merchant_id: string | null;
  active: boolean;
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
  provider: "gmail" | null;
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
  provider: "gmail" | null;
  provider_status: string | null;
  provider_draft_id: string | null;
  provider_message_id: string | null;
  provider_sent_at: string | null;
  provider_to_email: string | null;
};

export type GmailConnectionStatus = {
  connected: boolean;
  email_address: string | null;
  provider: "gmail";
  enabled: boolean;
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

export type GmailDraftSendResponse = {
  provider_draft_id: string;
  status: EmailProviderDraftStatus;
  provider_message_id: string | null;
  provider_thread_id: string | null;
  sent_at: string | null;
};

export type GmailInboundStatus = {
  enabled: boolean;
  connected: boolean;
  last_sync_at: string | null;
  last_success_at: string | null;
  status: GmailSyncStatus | null;
  last_error: string | null;
};

export type GmailInboundSyncPayload = {
  lookback_days?: number;
  max_messages?: number;
};

export type GmailInboundSyncResponse = {
  status: GmailSyncStatus;
  synced_messages: number;
  linked_messages: number;
  unlinked_messages: number;
  ignored_messages: number;
  errors: string[];
};

export type InboundEmailMessage = {
  id: number;
  email_account_id: number;
  order_id: number | null;
  provider: "gmail";
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
  orders_by_status: Record<string, number>;
  orders_by_restaurant: DashboardRestaurantSummary[];
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
  sender_email: string;
  uber_merchant_id?: string | null;
  active: boolean;
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
    super(formatApiError(detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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

export const api = {
  login: async (payload: LoginPayload) => {
    const response = await postJson<TokenResponse, LoginPayload>("/v1/auth/login", payload);
    setStoredToken(response.access_token);
    return response;
  },
  registerOwner: async (payload: RegisterOwnerPayload) => {
    const response = await postJson<TokenResponse, RegisterOwnerPayload>("/v1/auth/register", payload);
    setStoredToken(response.access_token);
    return response;
  },
  getMe: () => request<User>("/v1/auth/me"),
  logout: () => clearStoredToken(),
  getDashboardSummary: () => request<DashboardSummary>("/v1/dashboard/summary"),
  getRestaurants: () => request<Restaurant[]>("/v1/restaurants"),
  createRestaurant: (payload: RestaurantCreatePayload) =>
    postJson<Restaurant, RestaurantCreatePayload>("/v1/restaurants", payload),
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
  getInboundStatus: () => request<GmailInboundStatus>("/v1/email/gmail/inbound/status"),
  syncInboundGmail: (payload: GmailInboundSyncPayload = {}) =>
    postJson<GmailInboundSyncResponse, GmailInboundSyncPayload>("/v1/email/gmail/inbound/sync", payload),
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

export function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}
