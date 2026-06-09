"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type UberReportingImportBatch } from "@/lib/api";

export default function UberReportingPage() {
  const [batches, setBatches] = useState<UberReportingImportBatch[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getUberReportingBatches()
      .then(setBatches)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement imports Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Reporting imports</h1>
        </div>
        <Link className="button" href="/uber/reporting/new">
          Nouvel import
        </Link>
      </div>
      <ApiError error={error} />
      {batches.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fichier</th>
                <th>Type</th>
                <th>Statut</th>
                <th>Lignes</th>
                <th>Valides</th>
                <th>Invalides</th>
                <th>Warnings</th>
                <th>Snapshots</th>
                <th>Transactions</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.id}>
                  <td>{batch.original_filename}</td>
                  <td>{batch.report_type}</td>
                  <td><StatusBadge status={batch.status} /></td>
                  <td>{batch.total_rows}</td>
                  <td>{batch.valid_rows}</td>
                  <td>{batch.invalid_rows}</td>
                  <td>{batch.warning_rows}</td>
                  <td>{batch.created_snapshots_count}</td>
                  <td>{batch.created_transactions_count}</td>
                  <td>{formatDate(batch.created_at)}</td>
                  <td><Link className="secondary-button" href={`/uber/reporting/${batch.id}`}>Detail</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun import Uber reporting" />
      )}
    </section>
  );
}
