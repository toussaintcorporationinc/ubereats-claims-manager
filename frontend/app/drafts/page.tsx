"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type EmailDraftSummary } from "@/lib/api";

export default function DraftsPage() {
  const [drafts, setDrafts] = useState<EmailDraftSummary[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getDrafts()
      .then(setDrafts)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement des brouillons" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Brouillons</p>
          <h1>Brouillons internes</h1>
        </div>
      </div>

      <ApiError error={error} />

      {drafts.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Commande</th>
                <th>Restaurant</th>
                <th>Numero Uber</th>
                <th>Type</th>
                <th>Sujet</th>
                <th>Statut</th>
                <th>Creation</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((draft) => (
                <tr key={draft.id}>
                  <td>#{draft.order_id}</td>
                  <td>{draft.restaurant_name ?? "-"}</td>
                  <td>{draft.uber_order_number ?? "-"}</td>
                  <td>{draft.draft_type}</td>
                  <td>{draft.subject}</td>
                  <td>
                    <StatusBadge status={draft.status} />
                  </td>
                  <td>{formatDate(draft.created_at)}</td>
                  <td>
                    <Link href={`/orders/${draft.order_id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun brouillon" />
      )}
    </section>
  );
}
