"use client";

import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { formatCurrency, formatDate, type RecoveryAction, type WorkspaceAction } from "@/lib/api";

type Props = {
  action: RecoveryAction | WorkspaceAction;
};

export default function RecoveryActionCard({ action }: Props) {
  const href = "url" in action ? action.url : action.action_url;
  const label = "label" in action ? action.label : action.title;
  const description = "description" in action ? action.description : action.action_type;
  const restaurant = "restaurant_name" in action ? action.restaurant_name : action.restaurant;
  const dueAt = "due_at" in action ? action.due_at : null;

  return (
    <article className="premium-card recovery-action-card">
      <div className="card-row">
        <div>
          <h3>{label}</h3>
          <p className="muted">{description}</p>
        </div>
        <StatusBadge status={action.priority} />
      </div>
      <div className="card-row card-row--bottom">
        <div className="stack-sm">
          {restaurant ? <span>{restaurant}</span> : null}
          <span className="muted">{dueAt ? formatDate(dueAt) : actionTypeLabel(action.action_type)}</span>
        </div>
        <strong>{formatCurrency(action.amount)}</strong>
      </div>
      <Link href={href} className="button">
        Ouvrir
      </Link>
    </article>
  );
}

function actionTypeLabel(actionType: string): string {
  const labels: Record<string, string> = {
    upload_evidence: "Preuve a fournir",
    review_import: "Import a verifier",
    create_claim_order: "Dossier a creer",
    create_draft: "Email a preparer",
    connect_gmail: "Gmail a connecter",
    send_manual: "Email a envoyer",
    appeal_refusal: "Refus a reprendre",
    map_uber_store: "Restaurant a mapper",
    review_customer_refund: "Remboursement a verifier",
    export_report: "Rapport",
    manual_review: "A verifier",
  };
  return labels[actionType] ?? "Action TENNET";
}
