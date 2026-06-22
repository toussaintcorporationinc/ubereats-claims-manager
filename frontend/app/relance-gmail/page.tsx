"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import {
  api,
  formatCurrency,
  formatDate,
  formatDateTime,
  type GmailRelanceActionItem,
  type GmailRelanceDashboard,
  type GmailRelanceMessageItem,
  type GmailRelanceOrderSummary,
  type GmailRelanceSentItem,
} from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

export default function RelanceGmailPage() {
  const [dashboard, setDashboard] = useState<GmailRelanceDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadDashboard = useCallback(async (refreshStarred = false) => {
    if (refreshStarred) {
      setRefreshing(true);
    }
    try {
      const data = await api.getGmailRelanceDashboard(120, refreshStarred);
      setDashboard(data);
      setError(null);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
      if (refreshStarred) {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadDashboard(true);
    const interval = window.setInterval(() => {
      void loadDashboard(false);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [loadDashboard]);

  const workerState = dashboard?.worker.worker_state ?? "disabled";
  const workerTone = workerState === "active" ? "positive" : workerState === "attention" ? "warning" : "neutral";
  const lastUpdated = useMemo(() => formatDateTime(dashboard?.updated_at ?? null), [dashboard?.updated_at]);

  if (loading) {
    return <LoadingState label="Chargement relances Gmail" />;
  }

  return (
    <section className="page-section relance-gmail-page">
      <div className="page-heading relance-gmail-heading">
        <div className="heading-copy">
          <p className="eyebrow">Gmail / IA 24-7</p>
          <h1>Relance Gmail</h1>
          <p>
            Suivi en temps reel du travail Gmail: fils etoiles, relances envoyees, blocages reels,
            paiements detectes et comptes connectes.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadDashboard(true)} disabled={refreshing}>
          {refreshing ? "Actualisation..." : "Actualiser"}
        </button>
      </div>

      {error ? <ApiError error={error} /> : null}

      {dashboard ? (
        <>
          <section className={`gmail-worker-card gmail-worker-card--${workerState}`}>
            <div className="gmail-worker-card__header">
              <div>
                <span className="eyebrow">Surveillance active</span>
                <h2>{dashboard.worker.worker_message ?? "Etat Gmail"}</h2>
                <p>Derniere mise a jour: {lastUpdated}. Rafraichissement automatique toutes les 5 secondes.</p>
              </div>
              <span className={`status-pill status-pill--${workerTone}`}>
                {workerState === "active" ? "Actif" : workerState === "attention" ? "A verifier" : "Inactif"}
              </span>
            </div>
            <div className="gmail-worker-grid">
              <MetricCard label="Comptes Gmail" value={dashboard.summary.connected_accounts_count} detail={dashboard.worker.connected_account_emails.join(", ") || "-"} />
              <MetricCard label="Fils etoiles vus" value={dashboard.summary.starred_threads_seen} detail={`${dashboard.summary.unlinked_starred_threads} non rattache(s)`} />
              <MetricCard label="Relances 24h" value={dashboard.summary.sent_relances_last_24h} detail={`${dashboard.summary.latest_cycle_sent_count} dernier passage`} />
              <MetricCard label="Blocages 24h" value={dashboard.summary.blocked_actions_last_24h} detail={`${dashboard.summary.latest_cycle_skipped_count} saute(s), ${dashboard.summary.latest_cycle_failed_count} erreur(s)`} />
              <MetricCard label="Paiements detectes" value={dashboard.summary.payment_signals_last_24h} detail="signaux positifs 24h" />
            </div>
          </section>

          <div className="relance-gmail-grid">
            <section className="relance-feed relance-feed--wide">
              <FeedHeader title="Fils Gmail etoiles vus par TENNET" count={dashboard.starred_threads.length} />
              {dashboard.starred_threads.length > 0 ? (
                <div className="relance-card-list">
                  {dashboard.starred_threads.map((message) => (
                    <StarredThreadCard key={message.id} message={message} />
                  ))}
                </div>
              ) : (
                <EmptyState title="Aucun fil etoile charge" description="TENNET affichera ici les fils Gmail etoiles lus par la sync." />
              )}
            </section>

            <section className="relance-feed">
              <FeedHeader title="Relances envoyees ou brouillons Gmail" count={dashboard.sent_relances.length} />
              {dashboard.sent_relances.length > 0 ? (
                <div className="relance-card-list">
                  {dashboard.sent_relances.map((item) => (
                    <SentRelanceCard key={item.id} item={item} />
                  ))}
                </div>
              ) : (
                <EmptyState title="Aucune relance recente" description="Les envois Gmail apparaitront ici des que TENNET repond." />
              )}
            </section>

            <section className="relance-feed">
              <FeedHeader title="Actions AutoPilot et blocages" count={dashboard.recent_actions.length} />
              {dashboard.recent_actions.length > 0 ? (
                <div className="relance-card-list">
                  {dashboard.recent_actions.map((item) => (
                    <AutopilotActionCard key={item.id} item={item} />
                  ))}
                </div>
              ) : (
                <EmptyState title="Aucune action recente" description="Les relances, refus et blocages AutoPilot seront listes ici." />
              )}
            </section>
          </div>
        </>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: number | string; detail: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function FeedHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="relance-feed__header">
      <h2>{title}</h2>
      <span>{count}</span>
    </div>
  );
}

function StarredThreadCard({ message }: { message: GmailRelanceMessageItem }) {
  return (
    <article className="relance-card">
      <div className="relance-card__top">
        <div>
          <strong>{message.subject ?? "Sans objet"}</strong>
          <span>{message.account_email ?? `Compte #${message.email_account_id}`}</span>
        </div>
        <StatusPill value={message.analysis_type ?? message.match_status} />
      </div>
      <p>{message.snippet ?? "Aucun extrait disponible."}</p>
      <OrderLine order={message.order} />
      <div className="relance-meta">
        <span>{formatDateTime(message.received_at)}</span>
        <span>{message.from_email ?? "expediteur inconnu"}</span>
        <span>{message.match_status === "linked" ? "rattache" : "a rattacher"}</span>
      </div>
      {message.analysis_reason ? <small className="relance-note">{message.analysis_reason}</small> : null}
    </article>
  );
}

function SentRelanceCard({ item }: { item: GmailRelanceSentItem }) {
  return (
    <article className="relance-card">
      <div className="relance-card__top">
        <div>
          <strong>{item.subject}</strong>
          <span>{item.account_email ?? "Compte Gmail"}</span>
        </div>
        <StatusPill value={item.status} />
      </div>
      <OrderLine order={item.order} />
      <div className="relance-meta">
        <span>Vers {item.to_email}</span>
        <span>{formatDateTime(item.sent_at ?? item.updated_at)}</span>
      </div>
      {item.error_message || item.last_error ? (
        <small className="relance-note relance-note--warning">{item.error_message ?? item.last_error}</small>
      ) : null}
    </article>
  );
}

function AutopilotActionCard({ item }: { item: GmailRelanceActionItem }) {
  const reason = item.skipped_reason ?? item.reason;
  return (
    <article className="relance-card">
      <div className="relance-card__top">
        <div>
          <strong>{formatActionType(item.action_type)}</strong>
          <span>{item.restaurant_name ?? item.order?.restaurant_name ?? "Restaurant"}</span>
        </div>
        <StatusPill value={item.status} />
      </div>
      <OrderLine order={item.order} />
      <div className="relance-meta">
        <span>{formatDateTime(item.sent_at ?? item.updated_at)}</span>
        <span>Run #{item.run_id}</span>
      </div>
      {reason ? <small className="relance-note">{formatReason(reason)}</small> : null}
    </article>
  );
}

function OrderLine({ order }: { order: GmailRelanceOrderSummary | null }) {
  if (!order) {
    return <p className="relance-order relance-order--missing">Aucun dossier rattache pour l'instant.</p>;
  }
  const amount = formatCurrency(order.order_amount, order.currency ?? "EUR");
  return (
    <p className="relance-order">
      {order.restaurant_name ?? "Restaurant"} - {order.customer_name ?? "Client a confirmer"} -{" "}
      {order.uber_order_number ?? "Commande a confirmer"} - {order.order_date ? formatDate(order.order_date) : "Date a confirmer"} - {amount}
    </p>
  );
}

function StatusPill({ value }: { value: string }) {
  const tone = ["sent", "accepted", "payment_to_verify", "payment_confirmed", "linked"].includes(value)
    ? "positive"
    : ["skipped", "failed", "manual_review", "refused", "unlinked"].includes(value)
      ? "warning"
      : "neutral";
  return <span className={`status-pill status-pill--${tone}`}>{formatStatus(value)}</span>;
}

function formatStatus(value: string): string {
  const labels: Record<string, string> = {
    accepted: "positif",
    candidate: "candidat",
    draft_created: "brouillon",
    failed: "erreur",
    followup_needed: "relance",
    linked: "rattache",
    manual_review: "a verifier",
    payment_confirmed: "paiement confirme",
    payment_to_verify: "paiement a verifier",
    provider_draft_created: "brouillon Gmail",
    refused: "refus",
    send_requested: "envoi demande",
    sent: "envoye",
    skipped: "bloque",
    unlinked: "non rattache",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function formatActionType(value: string): string {
  const labels: Record<string, string> = {
    send_initial_claim: "Envoi demande",
    send_followup_1: "Relance 1",
    send_followup_2: "Relance 2",
    send_escalation: "Escalade",
    send_appeal: "Reponse au refus",
    request_more_evidence: "Preuve demandee",
    manual_review: "Verification humaine",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function formatReason(value: string): string {
  const labels: Record<string, string> = {
    cooldown_not_elapsed: "Cooldown encore actif.",
    gmail_account_not_connected: "Compte Gmail non connecte.",
    missing_restaurant_signature: "Signature restaurant incomplete.",
    no_new_argument_or_evidence: "Pas de nouvel argument ou element fiable.",
    positive_gmail_payment_signal_detected: "Paiement positif deja detecte.",
    starred_gmail_thread_required: "Fil Gmail etoile requis.",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}
