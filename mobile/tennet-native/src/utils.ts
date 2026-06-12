import { colors, statusColors } from "./theme";

export function formatCurrency(value: number | string | null | undefined, currency = "EUR"): string {
  const amount = Number(value ?? 0);
  if (!Number.isFinite(amount)) {
    return "0,00 EUR";
  }
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency,
  }).format(amount);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "Aucune date";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function labelForEvidence(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    receipt: "Ticket de caisse",
    cancellation_proof: "Preuve annulation",
    preparation_proof: "Preuve preparation",
    waste_photo: "Photo gaspillage",
    uber_screenshot: "Capture Uber",
    delivery_proof: "Preuve livraison",
    packaging_photo: "Photo emballage",
    sealed_bag_photo: "Sac scelle",
    order_details_screenshot: "Detail commande",
    courier_statement: "Message livreur",
    gps_or_route_proof: "Trace livraison",
    customer_contact_proof: "Contact client",
  };
  return labels[value ?? ""] ?? readableLabel(value);
}

export function readableLabel(value: string | null | undefined): string {
  if (!value) {
    return "A verifier";
  }
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace("Gmail", "Gmail");
}

export function colorForStatus(value: string | null | undefined): string {
  return statusColors[value ?? ""] ?? colors.inkMuted;
}

export function priorityRank(priority: string | null | undefined): number {
  const ranks: Record<string, number> = {
    urgent: 0,
    high: 1,
    normal: 2,
    low: 3,
  };
  return ranks[priority ?? "normal"] ?? 2;
}

export function getUploadTokenFromUrl(value: string): string | null {
  const trimmed = value.trim();
  const match = trimmed.match(/evidence-upload\/([^/?#]+)/);
  if (match?.[1]) {
    return decodeURIComponent(match[1]);
  }
  if (/^[A-Za-z0-9_-]{24,}$/.test(trimmed)) {
    return trimmed;
  }
  return null;
}
