"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDateTime, type AutopilotRunDetail } from "@/lib/api";

export default function AutopilotRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = Number(params.id);
  const [detail, setDetail] = useState<AutopilotRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const loadData = useCallback(async () => {
    const response = await api.getAutopilotRun(runId);
    setDetail(response);
  }, [runId]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  if (loading) {
    return <LoadingState label="Chargement run AutoPilot" />;
  }

  if (!detail) {
    return <EmptyState title="Run introuvable" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">AutoPilot</p>
          <h1>Run #{detail.run.id}</h1>
        </div>
        <div className="actions">
          <Link href="/autopilot" className="secondary-button">
            AutoPilot
          </Link>
          <Link href="/autopilot/runs" className="secondary-button">
            Runs
          </Link>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Resume</h2>
          <StatusBadge status={detail.run.status} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Mode" value={detail.run.mode} />
          <DetailItem label="Candidats" value={String(detail.run.total_candidates)} />
          <DetailItem label="Envoyes" value={String(detail.run.sent_count)} />
          <DetailItem label="Ignores" value={String(detail.run.skipped_count)} />
          <DetailItem label="Echecs" value={String(detail.run.failed_count)} />
          <DetailItem label="Cree" value={formatDateTime(detail.run.created_at)} />
        </div>
        {detail.run.error_message ? <div className="error-box">{detail.run.error_message}</div> : null}
      </section>

      {detail.actions.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Case</th>
                <th>Restaurant</th>
                <th>Statut</th>
                <th>Raison</th>
                <th>Draft</th>
                <th>Provider</th>
                <th>Envoye</th>
              </tr>
            </thead>
            <tbody>
              {detail.actions.map((action) => (
                <tr key={action.id}>
                  <td>{action.action_type}</td>
                  <td>
                    {action.case_type} #{action.case_id}
                  </td>
                  <td>{action.restaurant_id}</td>
                  <td>
                    <StatusBadge status={action.status} />
                  </td>
                  <td>{action.skipped_reason ?? action.reason}</td>
                  <td>{action.email_draft_id ?? "-"}</td>
                  <td>{action.provider_draft_id ?? "-"}</td>
                  <td>{formatDateTime(action.sent_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune action" />
      )}
    </section>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
