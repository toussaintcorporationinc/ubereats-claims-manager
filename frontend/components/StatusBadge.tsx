const positiveStatuses = new Set([
  "ready_to_send",
  "draft_email_created",
  "accepted",
  "payment_confirmed",
  "active",
  "created",
  "parsed",
  "confirmed",
  "provider_draft_created",
  "sent",
  "response_received",
  "evidence_ready",
  "linked",
  "success",
  "reviewed",
  "completed",
  "analyzed",
  "applied",
  "auto_attached",
  "accepted",
]);
const warningStatuses = new Set([
  "draft",
  "missing_evidence",
  "manual_review",
  "payment_to_verify",
  "uploaded",
  "partially_imported",
  "send_requested",
  "valid",
  "duplicate",
  "unauthorized",
  "running",
  "unlinked",
  "unreviewed",
  "evidence_requested",
  "information_requested",
  "followup_needed",
  "pending",
  "needs_evidence",
  "detected",
  "draft_created",
  "provider_draft_created",
  "payment_verification",
  "appeal_needed",
  "evidence_needed",
  "draft_needed",
  "gmail_draft_needed",
  "appeal_sent",
  "escalated",
  "under_appeal",
  "analysis_pending",
  "manual_review",
  "high",
  "normal",
]);
const closedStatuses = new Set(["refused", "closed", "inactive", "failed", "cancelled", "invalid", "skipped", "ignored", "low"]);

export default function StatusBadge({ status }: { status: string }) {
  const tone = positiveStatuses.has(status)
    ? "positive"
    : warningStatuses.has(status)
      ? "warning"
      : closedStatuses.has(status)
        ? "closed"
        : "neutral";

  return <span className={`status-badge status-badge--${tone}`}>{status.replaceAll("_", " ")}</span>;
}
