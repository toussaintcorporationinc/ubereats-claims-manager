"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type ImportBatch } from "@/lib/api";

export default function ImportsPage() {
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getImportBatches()
      .then(setBatches)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement des imports" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Imports</p>
          <h1>Imports commandes</h1>
        </div>
        <Link href="/imports/new" className="button">
          Nouvel import
        </Link>
      </div>

      <ApiError error={error} />

      {batches.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fichier</th>
                <th>Statut</th>
                <th>Total</th>
                <th>Valides</th>
                <th>Invalides</th>
                <th>Doublons</th>
                <th>Non autorisees</th>
                <th>Creees</th>
                <th>Date</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.id}>
                  <td>{batch.original_filename}</td>
                  <td>
                    <StatusBadge status={batch.status} />
                  </td>
                  <td>{batch.total_rows}</td>
                  <td>{batch.valid_rows}</td>
                  <td>{batch.invalid_rows}</td>
                  <td>{batch.duplicate_rows}</td>
                  <td>{batch.unauthorized_rows}</td>
                  <td>{batch.created_orders_count}</td>
                  <td>{formatDate(batch.created_at)}</td>
                  <td>
                    <Link href={`/imports/${batch.id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun import" />
      )}
    </section>
  );
}
