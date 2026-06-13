"use client";

import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { formatCurrency, formatDate, type EvidenceRequestTaskSummary } from "@/lib/api";

type Props = {
  task: EvidenceRequestTaskSummary;
};

export default function EvidenceTaskCard({ task }: Props) {
  return (
    <article className="premium-card evidence-task-card">
      <div className="card-row">
        <div>
          <h3>{task.title}</h3>
          <p className="muted">{task.restaurant_name}</p>
        </div>
        <StatusBadge status={task.priority} />
      </div>
      <div className="detail-grid detail-grid--compact">
        <div className="detail-item">
          <span>Commande</span>
          <strong>{formatOrderIdentity(task.customer_name, task.uber_order_number)}</strong>
        </div>
        <div className="detail-item">
          <span>Montant</span>
          <strong>{formatCurrency(task.order_amount, task.currency)}</strong>
        </div>
        <div className="detail-item">
          <span>Echeance</span>
          <strong>{formatDate(task.due_at)}</strong>
        </div>
      </div>
      <div className="card-row card-row--bottom">
        <StatusBadge status={task.status} />
        <span className="muted">{task.required_evidence_type}</span>
      </div>
      <Link href={`/evidence-tasks/${task.id}`} className="button">
        Ouvrir
      </Link>
    </article>
  );
}

function formatOrderIdentity(customerName: string | null, orderNumber: string): string {
  return customerName ? `${customerName} - ${orderNumber}` : orderNumber;
}
