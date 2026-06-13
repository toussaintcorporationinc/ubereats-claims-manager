"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type EvidenceImportBatch } from "@/lib/api";

export default function EvidenceImportsPage() {
  const [batches, setBatches] = useState<EvidenceImportBatch[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    const response = await api.getEvidenceImports({ limit: 100 });
    setBatches(response.batches);
  }, []);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  if (loading) {
    return <LoadingState label="Chargement imports preuves" />;
  }

  const totalFiles = batches.reduce((total, batch) => total + batch.total_files, 0);
  const needsReview = batches.reduce((total, batch) => total + batch.needs_review_count, 0);
  const duplicatesRemoved = batches.reduce((total, batch) => total + batch.duplicate_files_count, 0);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuves</p>
          <h1>Import massif preuves</h1>
          <p>Importez tickets, photos, PDF et captures en vrac. TENNET propose les rattachements sans inventer de preuve.</p>
        </div>
        <Link href="/evidence-imports/new" className="button">
          Nouvel import
        </Link>
      </div>

      <ApiError error={error} />

      <div className="stats-grid">
        <StatCard label="Batches" value={batches.length} />
        <StatCard label="Fichiers" value={totalFiles} />
        <StatCard label="A revoir" value={needsReview} />
        <StatCard label="Doublons supprimes" value={duplicatesRemoved} />
      </div>

      <section className="tool-panel">
        <h2>Imports</h2>
        {batches.length === 0 ? (
          <EmptyState title="Aucun import de preuves" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Source</th>
                  <th>Statut</th>
                  <th>Fichiers</th>
                  <th>Analyses</th>
                  <th>A revoir</th>
                  <th>Doublons</th>
                  <th>Echecs</th>
                  <th>Date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr key={batch.id}>
                    <td>#{batch.id}</td>
                    <td>{batch.source_type}</td>
                    <td>
                      <StatusBadge status={batch.status} />
                    </td>
                    <td>{batch.stored_files_count}/{batch.total_files}</td>
                    <td>{batch.analyzed_files_count}</td>
                    <td>{batch.needs_review_count}</td>
                    <td>{batch.duplicate_files_count}</td>
                    <td>{batch.failed_files_count}</td>
                    <td>{formatDate(batch.created_at)}</td>
                    <td>
                      <Link href={`/evidence-imports/${batch.id}`} className="secondary-button">
                        Ouvrir
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
