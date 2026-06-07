const positiveStatuses = new Set([
  "ready_to_send",
  "draft_email_created",
  "accepted",
  "payment_confirmed",
  "active",
  "created",
  "parsed",
  "confirmed",
]);
const warningStatuses = new Set([
  "draft",
  "missing_evidence",
  "manual_review",
  "payment_to_verify",
  "uploaded",
  "partially_imported",
  "valid",
  "duplicate",
  "unauthorized",
]);
const closedStatuses = new Set(["refused", "closed", "inactive", "failed", "cancelled", "invalid", "skipped"]);

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
