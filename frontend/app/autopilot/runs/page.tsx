"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDateTime, type AutopilotRun } from "@/lib/api";

export default function AutopilotRunsPage() {
  const [runs, setRuns] = useState<AutopilotRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const loadData = useCallback(async () => {
    const response = await api.getAutopilotRuns({ limit: 100 });
    setRuns(response.runs);
  }, []);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  if (loading) {
    return <LoadingState label="Chargement runs AutoPilot" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">AutoPilot</p>
          <h1>Historique des runs</h1>
        </div>
        <Link href="/autopilot" className="secondary-button">
          Retour AutoPilot
        </Link>
      </div>

      <ApiError error={error} />

      {runs.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Mode</th>
                <th>Statut</th>
                <th>Candidats</th>
                <th>Envoyes</th>
                <th>Ignores</th>
                <th>Echecs</th>
                <th>Date</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>#{run.id}</td>
                  <td>{run.mode}</td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>{run.total_candidates}</td>
                  <td>{run.sent_count}</td>
                  <td>{run.skipped_count}</td>
                  <td>{run.failed_count}</td>
                  <td>{formatDateTime(run.created_at)}</td>
                  <td>
                    <Link href={`/autopilot/runs/${run.id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun run AutoPilot" />
      )}
    </section>
  );
}
