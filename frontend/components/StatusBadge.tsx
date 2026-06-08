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
  "linked",
  "success",
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
]);
const closedStatuses = new Set(["refused", "closed", "inactive", "failed", "cancelled", "invalid", "skipped", "ignored"]);

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
