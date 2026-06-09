"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatCurrency, formatDate, type UberReconciliationRun } from "@/lib/api";

export default function UberReconciliationRunsPage() {
  const [runs, setRuns] = useState<UberReconciliationRun[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getUberReconciliationRuns()
      .then(setRuns)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement analyses Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Analyses reconciliation</h1>
        </div>
        <Link className="button" href="/uber/reconciliation">
          Nouvelle analyse
        </Link>
      </div>
      <ApiError error={error} />
      {runs.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Periode</th>
                <th>Statut</th>
                <th>Commandes</th>
                <th>Annulees</th>
                <th>Manquant</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{formatDate(run.created_at)}</td>
                  <td>
                    {formatDate(run.date_from)} - {formatDate(run.date_to)}
                  </td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>{run.total_orders_analyzed}</td>
                  <td>{run.canceled_orders_count}</td>
                  <td>{formatCurrency(run.total_missing_amount)}</td>
                  <td>
                    <Link className="secondary-button" href={`/uber/reconciliation/runs/${run.id}`}>
                      Detail
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune analyse" />
      )}
    </section>
  );
}
