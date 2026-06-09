"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { api, formatCurrency, formatDate, type AppealDetailResponse, type AppealType, type GmailConnectionStatus } from "@/lib/api";

type PageProps = { params: Promise<{ id: string }> };

const appealTypes: AppealType[] = ["first_appeal", "second_appeal", "evidence_reply", "escalation", "payment_verification", "manager_review"];

export default function AppealDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const workflowId = Number(id);
  const [detail, setDetail] = useState<AppealDetailResponse | null>(null);
  const [appealType, setAppealType] = useState<AppealType>("first_appeal");
  const [manualReason, setManualReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);
  const [gmailStatus, setGmailStatus] = useState<GmailConnectionStatus | null>(null);

  const loadData = useCallback(async () => {
    const [appealDetail, emailStatus] = await Promise.all([api.getAppeal(workflowId), api.getGmailStatus().catch(() => null)]);
    setDetail(appealDetail);
    setGmailStatus(emailStatus);
  }, [workflowId]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function runAction(action: string, callback: () => Promise<unknown>) {
    setWorking(action);
    setError(null);
    try {
      await callback();
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement appel" />;
  }

  const workflow = detail?.workflow;
  const amount = detail?.case_summary.amount as string | number | null | undefined;
  const currency = (detail?.case_summary.currency as string | undefined) ?? "EUR";
  const gmailDisabled = gmailStatus?.enabled === false;
  const gmailNotConnected = gmailStatus?.enabled === true && gmailStatus.connected === false;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Appels</p>
          <h1>Workflow #{workflowId}</h1>
          <p>Aucun email n'est envoye automatiquement.</p>
        </div>
        <Link href="/appeals" className="secondary-button">
          Retour
        </Link>
      </div>

      <ApiError error={error} />

      {workflow && detail ? (
        <>
          <div className="stats-grid">
            <StatCard label="Montant" value={formatCurrency(amount ?? null, currency)} />
            <StatCard label="Refus" value={workflow.refusal_count} />
            <StatCard label="Tentatives" value={workflow.appeal_attempt_count} />
            <StatCard label="Action" value={workflow.next_action_type ?? "-"} />
            <StatCard label="Statut" value={workflow.status} />
          </div>

          <section className="tool-panel">
            <div className="section-heading">
              <h2>Dossier</h2>
              <StatusBadge status={workflow.status} />
            </div>
            <p>Restaurant : <strong>{String(detail.case_summary.restaurant_name ?? "-")}</strong></p>
            <p>Commande : <strong>{String(detail.case_summary.uber_order_number ?? "-")}</strong></p>
            <p>Type : <strong>{workflow.case_type}</strong></p>
            <Link href={String(detail.case_summary.link_url ?? "/recovery")} className="secondary-button">
              Ouvrir dossier lie
            </Link>
          </section>

          <section className="tool-panel">
            <h2>Actions controlees</h2>
            <div className="filters">
              <div className="field">
                <label htmlFor="appeal_type">Type brouillon</label>
                <select id="appeal_type" value={appealType} onChange={(event) => setAppealType(event.target.value as AppealType)}>
                  {appealTypes.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>
              <button type="button" className="secondary-button" disabled={Boolean(working)} onClick={() => runAction("analyze", () => api.analyzeAppealRefusal(workflow.id))}>
                Analyser refus
              </button>
              <button type="button" className="button" disabled={Boolean(working)} onClick={() => runAction("draft", () => api.createAppealDraft(workflow.id, { appeal_type: appealType }))}>
                Creer brouillon appel
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={Boolean(working) || gmailDisabled || gmailNotConnected}
                onClick={() => runAction("gmail", () => api.createAppealGmailDraft(workflow.id))}
              >
                Creer brouillon Gmail
              </button>
              <button type="button" className="secondary-button" disabled={Boolean(working)} onClick={() => runAction("sent", () => api.markAppealSent(workflow.id))}>
                Marquer envoye
              </button>
            </div>
            {gmailDisabled ? <p className="muted-text">Gmail est desactive sur cet environnement.</p> : null}
            {gmailNotConnected ? <p className="muted-text">Compte Gmail non connecte.</p> : null}
            <div className="inline-form">
              <label htmlFor="manual_reason">Raison pause / cloture</label>
              <input id="manual_reason" value={manualReason} onChange={(event) => setManualReason(event.target.value)} />
              <div className="actions">
                <button type="button" className="secondary-button" disabled={Boolean(working) || !manualReason} onClick={() => runAction("pause", () => api.pauseAppeal(workflow.id, { reason: manualReason }))}>
                  Pause
                </button>
                <button type="button" className="danger-button" disabled={Boolean(working) || !manualReason} onClick={() => runAction("close", () => api.manualCloseAppeal(workflow.id, { reason: manualReason }))}>
                  Cloture owner
                </button>
                <button type="button" className="secondary-button" disabled={Boolean(working)} onClick={() => runAction("reopen", () => api.reopenAppeal(workflow.id))}>
                  Reouvrir
                </button>
              </div>
            </div>
          </section>

          <div className="grid-two">
            <section className="tool-panel">
              <h2>Analyses refus</h2>
              {detail.refusal_analyses.length === 0 ? (
                <EmptyState title="Aucune analyse" />
              ) : (
                detail.refusal_analyses.map((analysis) => (
                  <div key={analysis.id} className="list-row">
                    <strong>{analysis.recommended_next_action}</strong>
                    <span>{analysis.refusal_reason}</span>
                    <span>{analysis.required_evidence_types_json?.join(", ") ?? "-"}</span>
                  </div>
                ))
              )}
            </section>
            <section className="tool-panel">
              <h2>Tentatives</h2>
              {detail.attempts.length === 0 ? (
                <EmptyState title="Aucune tentative" />
              ) : (
                detail.attempts.map((attempt) => (
                  <div key={attempt.id} className="list-row">
                    <strong>#{attempt.attempt_number} {attempt.appeal_type}</strong>
                    <StatusBadge status={attempt.status} />
                    <span>{formatDate(attempt.created_at)}</span>
                  </div>
                ))
              )}
            </section>
          </div>
        </>
      ) : null}
    </section>
  );
}
