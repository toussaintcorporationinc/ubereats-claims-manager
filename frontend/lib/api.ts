const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type MoneyValue = string | number | null;

export type ClaimOrderStatus =
  | "draft"
  | "missing_evidence"
  | "ready_to_send"
  | "draft_email_created"
  | "sent"
  | "waiting_uber_response"
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
  mime_type: string | null;
  file_size: number | null;
  uploaded_at: string;
};

export type EmailDraft = {
  id: number;
  order_id: number;
  draft_type: EmailDraftType;
  subject: string;
  body: string;
  status: string;
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
  orders_by_status: Record<string, number>;
  orders_by_restaurant: DashboardRestaurantSummary[];
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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
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
  getDashboardSummary: () => request<DashboardSummary>("/v1/dashboard/summary"),
  getRestaurants: () => request<Restaurant[]>("/v1/restaurants"),
  createRestaurant: (payload: RestaurantCreatePayload) =>
    postJson<Restaurant, RestaurantCreatePayload>("/v1/restaurants", payload),
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
  validateOrder: (id: number) =>
    postJson<ClaimValidationResponse, Record<string, never>>(`/v1/orders/${id}/validate`, {}),
  createOrderDraft: (id: number, draftType: EmailDraftType) =>
    postJson<EmailDraft, { draft_type: EmailDraftType }>(`/v1/orders/${id}/drafts`, {
      draft_type: draftType,
    }),
  getOrderDrafts: (id: number) => request<EmailDraft[]>(`/v1/orders/${id}/drafts`),
  getDrafts: () => request<EmailDraftSummary[]>("/v1/drafts"),
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
