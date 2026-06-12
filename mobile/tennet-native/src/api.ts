import * as SecureStore from "expo-secure-store";

const SESSION_KEY = "tennet_mobile_session";

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? "https://api.thetennet.com";
export const WEB_APP_URL = process.env.EXPO_PUBLIC_WEB_APP_URL ?? "https://app.thetennet.com";

export type User = {
  id: number;
  email: string;
  full_name: string | null;
  role: "owner" | "manager" | "staff";
  active: boolean;
};

export type Session = {
  access_token: string;
  token_type: string;
  user: User;
};

export type EvidenceTask = {
  id: number;
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  order_amount: number | string | null;
  currency: string;
  claim_status?: string;
  task_type: string;
  required_evidence_type: string;
  status: string;
  priority: string;
  due_at: string | null;
  title: string;
  description: string | null;
  reason: string;
  created_at: string;
  updated_at: string;
};

export type EvidenceTasksResponse = {
  tasks: EvidenceTask[];
  limit: number;
  offset: number;
};

export type EvidencePrintTicket = {
  task_id: number;
  order_id: number;
  restaurant_id: number;
  restaurant_name: string;
  uber_order_number: string;
  required_evidence_type: string;
  required_evidence_label: string;
  title: string;
  description: string | null;
  order_amount: number | string | null;
  currency: string;
  due_at: string | null;
  ticket_reference: string;
  upload_url: string;
  qr_svg: string;
  print_html: string;
};

export type DashboardSummary = {
  total_orders: number;
  total_claimed_amount: number | string;
  total_recovered_amount: number | string;
  total_pending_amount: number | string;
  followups_due_count: number;
  manual_review_due_count: number;
  success_rate: number | string;
};

export type WorkspaceAction = {
  title: string;
  description: string;
  restaurant: string | null;
  amount: number | string | null;
  priority: string;
  action_url: string;
  action_type: string;
};

export type WorkspaceNextActions = {
  urgent: WorkspaceAction[];
  today: WorkspaceAction[];
  this_week: WorkspaceAction[];
  blocked: WorkspaceAction[];
  high_value: WorkspaceAction[];
};

export type RecoveryTotals = {
  detected_amount: number | string;
  claimable_amount: number | string;
  missing_evidence_amount: number | string;
  sent_amount: number | string;
  recovered_amount: number | string;
  refused_amount: number | string;
  pending_amount: number | string;
  detected_count: number;
  missing_evidence_count: number;
  manual_review_count: number;
  active_appeals_count: number;
  recovery_rate: number | string;
};

export type RecoverySummary = {
  totals: RecoveryTotals;
  top_recoverable_cases: RecoveryCase[];
};

export type RecoveryCase = {
  case_type: string;
  case_id: number;
  restaurant_name: string;
  uber_order_number: string | null;
  loss_category: string;
  recovery_stage: string;
  detected_amount: number | string;
  claimable_amount: number | string;
  recovered_amount: number | string;
  status: string;
  evidence_status: string | null;
  next_action: string | null;
  created_at: string;
  link_url: string;
};

export type RecoveryAction = {
  action_type: string;
  case_type: string;
  case_id: number;
  restaurant_name: string;
  priority: string;
  amount: number | string;
  due_at: string | null;
  label: string;
  url: string;
};

export type RecoveryActionsResponse = {
  actions: RecoveryAction[];
  limit: number;
  offset: number;
};

export type PublicEvidenceUploadLink = {
  task_id: number;
  order_id: number;
  restaurant_name: string;
  uber_order_number: string;
  required_evidence_type: string;
  status: string;
  priority: string;
  title: string;
  description: string | null;
  expires_at: string;
  max_uses: number;
  use_count: number;
};

export type UploadableFile = {
  uri: string;
  name: string;
  type: string;
};

export async function saveSession(session: Session): Promise<void> {
  await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
}

export async function loadSession(): Promise<Session | null> {
  const raw = await SecureStore.getItemAsync(SESSION_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as Session;
  } catch {
    await SecureStore.deleteItemAsync(SESSION_KEY);
    return null;
  }
}

export async function clearSession(): Promise<void> {
  await SecureStore.deleteItemAsync(SESSION_KEY);
}

export async function login(email: string, password: string): Promise<Session> {
  const session = await request<Session>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  await saveSession(session);
  return session;
}

export async function request<T>(path: string, init: RequestInit = {}, session?: Session | null): Promise<T> {
  const activeSession = session === undefined ? await loadSession() : session;
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  if (activeSession?.access_token) {
    headers.set("Authorization", `Bearer ${activeSession.access_token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });
  const text = await response.text();
  const payload = text ? safeJson(text) : null;
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? String(payload.detail) : response.statusText;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload as T;
}

export async function uploadFile<T>(path: string, file: UploadableFile, session?: Session | null): Promise<T> {
  const body = new FormData();
  body.append("file", file as unknown as Blob);
  return request<T>(
    path,
    {
      method: "POST",
      body,
    },
    session,
  );
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
