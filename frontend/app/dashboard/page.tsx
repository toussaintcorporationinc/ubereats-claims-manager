"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import {
  api,
  formatCurrency,
  formatDateTime,
  type DashboardSummary,
  type GmailWarRoomDashboard,
} from "@/lib/api";

const POLL_INTERVAL_MS = 10000;

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [warRoom, setWarRoom] = useState<GmailWarRoomDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadDashboard = useCallback(async () => {
    try {
      const [dashboardSummary, gmailWarRoom] = await Promise.all([
        api.getDashboardSummary(),
        api.getGmailWarRoom(80, false),
      ]);
      setSummary(dashboardSummary);
      setWarRoom(gmailWarRoom);
      setError(null);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
    const interval = window.setInterval(() => {
      void loadDashboard();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [loadDashboard]);

  const processedLast24h = warRoom?.summary.processed_messages_last_24h ?? 0;
  const dailyTarget = warRoom?.summary.daily_processing_target ?? 2000;
  const progressPercent = useMemo(() => {
    if (warRoom?.summary.processed_progress_percent !== undefined) {
      return warRoom.summary.processed_progress_percent;
    }
    return Math.min(100, Math.round((processedLast24h / Math.max(dailyTarget, 1)) * 100));
  }, [dailyTarget, processedLast24h, warRoom?.summary.processed_progress_percent]);

  if (loading) {
    return <LoadingState label="Chargement de l'assistant Gmail" />;
  }

  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero machine-hero--focus machine-hero--home">
        <div className="machine-hero__main machine-hero__main--simple">
          <div className="heading-copy">
            <p className="eyebrow">Assistant Gmail 24/7</p>
            <h1>Accueil TENNET</h1>
            <p>
              TENNET se concentre sur Gmail: fils etoiles, refus Uber, relances,
              reponses positives et montants accordes. L'ancienne machinerie
              d'import n'est plus le centre de l'application.
            </p>
          </div>

          <div className={`machine-command ${warRoom?.worker.worker_state === "active" ? "machine-command--running" : ""}`}>
            <div className="machine-ring" aria-hidden="true">
              <span />
            </div>
            <div className="machine-command__content">
              <strong>{warRoom?.worker.worker_state === "active" ? "Gmail actif" : "Gmail a verifier"}</strong>
              <span>
                {processedLast24h} / {dailyTarget} traites en 24h
              </span>
            </div>
          </div>

          <div className="home-machine-status">
            <strong>{warRoom?.summary.quota_blocked ? "Quota Gmail en pause" : "Surveillance continue"}</strong>
            <p>
              {warRoom?.summary.quota_blocked
                ? `Reprise automatique: ${formatDateTime(warRoom.summary.quota_retry_after)}`
                : "Les fils etoiles restent surveilles; les positifs sont comptabilises et les refus restent actifs."}
            </p>
          </div>
        </div>
      </div>

      {error ? <ApiError error={error} /> : null}

      <div className="stats-grid">
        <StatCard
          label="Threads surveilles"
          value={warRoom?.summary.active_watched_threads ?? 0}
          detail={`${warRoom?.summary.watched_threads_total ?? 0} connus`}
        />
        <StatCard label="Traites 24h" value={`${processedLast24h}/${dailyTarget}`} detail={`${progressPercent}% de l'objectif`} />
        <StatCard
          label="Relances 24h"
          value={`${warRoom?.summary.sent_relances_last_24h ?? 0}/${warRoom?.summary.daily_send_capacity ?? 0}`}
          detail={`${warRoom?.summary.remaining_send_capacity_today ?? 0} restantes`}
        />
        <StatCard
          label="Paiements detectes"
          value={warRoom?.summary.positive_responses_last_24h ?? 0}
          detail="signaux positifs 24h"
        />
        <StatCard label="Backlog" value={warRoom?.summary.backlog_remaining ?? 0} detail="reste a traiter" />
        <StatCard
          label="Comptes Gmail"
          value={warRoom?.summary.connected_accounts_count ?? 0}
          detail={warRoom?.worker.connected_account_emails.join(", ") || "-"}
        />
      </div>

      <div className="grid-two">
        <section className="tool-panel">
          <h2>Finance</h2>
          <p className="muted">Montants calcules depuis les reponses positives, refus et dossiers suivis.</p>
          <div className="stats-grid">
            <StatCard label="Paiements confirmes" value={formatCurrency(summary?.total_recovered_amount ?? 0)} />
            <StatCard label="A suivre" value={formatCurrency(summary?.total_pending_amount ?? 0)} />
            <StatCard label="Refuse" value={formatCurrency(summary?.total_refused_amount ?? 0)} />
            <StatCard label="Dossiers visibles" value={summary?.total_orders ?? 0} />
          </div>
          <Link href="/finance" className="secondary-button">
            Voir Finance
          </Link>
        </section>

        <section className="tool-panel">
          <h2>Relance Gmail</h2>
          <p className="muted">
            Threads surveilles, relances envoyees, quota Gmail, paiements detectes et blocages reels.
          </p>
          <Link href="/relance-gmail" className="button button--hero">
            Ouvrir Relance Gmail
          </Link>
        </section>
      </div>
    </section>
  );
}
