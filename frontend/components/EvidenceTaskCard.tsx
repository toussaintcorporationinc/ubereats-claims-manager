"use client";

import Link from "next/link";
import StatusBadge from "@/components/StatusBadge";
import { formatDate, type EvidenceRequestTaskSummary } from "@/lib/api";

type Props = {
  task: EvidenceRequestTaskSummary;
};

export default function EvidenceTaskCard({ task }: Props) {
  return (
    <article className="premium-card evidence-task-card">
      <div className="card-row">
        <div>
          <h3>{task.field_context_label}</h3>
          <p className="muted">{task.field_photo_instruction}</p>
        </div>
        <StatusBadge status={task.priority} />
      </div>
      <div className="detail-grid detail-grid--compact">
        <div className="detail-item">
          <span>Restaurant</span>
          <strong>{task.field_restaurant_label}</strong>
        </div>
        <div className="detail-item detail-item--wide">
          <span>Client</span>
          <strong>{task.field_customer_label}</strong>
        </div>
        <div className="detail-item">
          <span>Commande Uber</span>
          <strong>{task.field_order_label}</strong>
        </div>
        <div className="detail-item">
          <span>Date</span>
          <strong>{task.field_date_label}</strong>
        </div>
        <div className="detail-item">
          <span>Montant</span>
          <strong>{task.field_amount_label}</strong>
        </div>
        <div className="detail-item">
          <span>Echeance</span>
          <strong>{formatDate(task.due_at)}</strong>
        </div>
      </div>
      <div className="field-search-hint">
        <span>A chercher dans Uber</span>
        <strong>{task.field_search_hint}</strong>
      </div>
      <div className="card-row card-row--bottom">
        <StatusBadge status={task.status} />
        <span className="muted">{task.title}</span>
      </div>
      <Link href={`/evidence-tasks/${task.id}`} className="button">
        Ouvrir
      </Link>
    </article>
  );
}
