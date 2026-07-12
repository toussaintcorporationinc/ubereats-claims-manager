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
  type GmailRelanceOrderSummary,
  type GmailRelanceSentItem,
  type GmailWarRoomDashboard,
  type GmailWatchedThreadItem,
  type GmailWatchedWorkItem,
} from "@/lib/api";

const POLL_INTERVAL_MS = 5000;

export default function GmailWarRoomPage() {
  const [dashboard, setDashboard] = useState<GmailWarRoomDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadDashboard = useCallback(async (refresh = false) => {
    if (refresh) {
      setRefreshing(true);
    }

    try {
      const data = await api.getGmailWarRoom(180, refresh);
      setDashboard(data);
      setError(null);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
      if (refresh) {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void loadDashboard(false);
    const interval = window.setInterval(() => {
      void loadDashboard(false);
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [loadDashboard]);

  const workerState = dashboard?.worker.worker_state ?? "disabled";
  const workerTone = workerState === "active" ? "positive" : workerState === "attention" ? "warning" : "neutral";
  const lastUpdated = useMemo(() => formatDateTime(dashboard?.updated_at ?? null), [dashboard?.updated_at]);

  if (loading) {
    return <LoadingState label="Chargement War Room Gmail" />;
  }

  return (
    <section className="page-section relance-gmail-page">
      <div className="page-heading relance-gmail-heading">
        <div className="heading-copy">
          <p className="eyebrow">Gmail / IA 24-7</p>
          <h1>Relance Gmail</h1>
          <p>
            Suivi temps reel des threads etoiles, nouvelles reponses Uber, paiements detectes,
            refus a relancer et blocages reels.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadDashboard(true)} disabled={refreshing}>
          {refreshing ? "Actualisation..." : "Forcer un passage"}
        </button>
      </div>

      {error ? <ApiError error={error} /> : null}

      {dashboard ? (
        <>
          <section className={`gmail-worker-card gmail-worker-card--${workerState}`}>
            <div className="gmail-worker-card__header">
              <div>
                <span className="eyebrow">Surveillance active</span>
                <h2>{dashboard.worker.worker_message ?? "TENNET surveille Gmail automatiquement."}</h2>
                <p>Derniere mise a jour: {lastUpdated}. Rafraichissement visuel toutes les 5 secondes.</p>
              </div>
              <span className={`status-pill status-pill--${workerTone}`}>
                {workerState === "active" ? "Actif" : workerState === "attention" ? "A verifier" : "Inactif"}
              </span>
            </div>
            <div className="gmail-worker-grid">
              <MetricCard
                label="Comptes Gmail"
                value={dashboard.summary.connected_accounts_count}
                detail={dashboard.worker.connected_account_emails.join(", ") || "-"}
              />
              <MetricCard
                label="Threads surveilles"
                value={dashboard.summary.active_watched_threads}
                detail={`${dashboard.summary.watched_threads_total} thread(s) connus`}
              />
              <MetricCard
                label="Nouvelles reponses 24h"
                value={dashboard.summary.new_messages_detected_last_24h}
                detail={`${dashboard.summary.processed_messages_last_24h} traitee(s)`}
              />
              <MetricCard
                label="Objectif 24h"
                value={`${dashboard.summary.processed_messages_last_24h}/${dashboard.summary.daily_processing_target}`}
                detail={`${dashboard.summary.processed_progress_percent}% de l'objectif`}
              />
              <MetricCard
                label="Relances 24h"
                value={`${dashboard.summary.sent_relances_last_24h}/${dashboard.summary.daily_send_capacity}`}
                detail={`${dashboard.summary.remaining_send_capacity_today} restante(s)`}
              />
              <MetricCard
                label="Refus 24h"
                value={dashboard.summary.refused_responses_last_24h}
                detail={`${dashboard.summary.positive_responses_last_24h} positif(s)`}
              />
              <MetricCard
                label="Backlog restant"
                value={dashboard.summary.backlog_remaining}
                detail={`${dashboard.summary.manual_review_last_24h} a verifier`}
              />
              <MetricCard
                label="Quota Gmail"
                value={dashboard.summary.quota_blocked ? "En pause" : "OK"}
                detail={
                  dashboard.summary.quota_blocked
                    ? `Reprise ${formatDateTime(dashboard.summary.quota_retry_after)}`
                    : "quota disponible"
                }
              />
            </div>
          </section>

          <div className="relance-gmail-grid">
            <section className="relance-feed relance-feed--wide">
              <FeedHeader title="Threads etoiles surveilles" count={dashboard.watched_threads.length} />
              {dashboard.watched_threads.length > 0 ? (
                <div className="relance-card-list">
                  {dashboard.watched_threads.map((thread) => (
                    <WatchedThreadCard key={thread.id} thread={thread} />
                  ))}
                </div>
              ) : (
                <EmptyState title="Aucun thread surveille" description="Une etoile Gmail ajoute automatiquement le fil ici au prochain passage." />
              )}
            </section>

            <section className="relance-feed">
              <FeedHeader title="Messages traites ou bloques" count={dashboard.work_items.length} />
              {dashboard.work_items.length > 0 ? (
                <div className="relance-card-list">
                  {dashboard.work_items.map((item) => (
                    <WorkItemCard key={item.id} item={item} />
                  ))}
                </div>
              ) : (
                <EmptyState title="Aucun message traite" description="Les nouvelles reponses de threads surveilles apparaitront ici." />
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
                <EmptyState title="Aucune relance recente" description="Les reponses Gmail envoyees par TENNET apparaitront ici." />
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

function WatchedThreadCard({ thread }: { thread: GmailWatchedThreadItem }) {
  return (
    <article className="relance-card">
      <div className="relance-card__top">
        <div>
          <strong>{thread.order?.uber_order_number ?? thread.gmail_thread_id}</strong>
          <span>{thread.account_email ?? `Compte #${thread.email_account_id}`}</span>
        </div>
        <StatusPill value={thread.status} />
      </div>
      <OrderLine order={thread.order} />
      <div className="relance-meta">
        <span>{thread.star_active ? "etoile active" : "etoile retiree"}</span>
        <span>Dernier mail: {formatDateTime(thread.last_message_at)}</span>
        <span>Traite: {formatDateTime(thread.last_processed_at)}</span>
      </div>
    </article>
  );
}

function WorkItemCard({ item }: { item: GmailWatchedWorkItem }) {
  return (
    <article className="relance-card">
      <div className="relance-card__top">
        <div>
          <strong>{item.subject ?? "Sans objet"}</strong>
          <span>{item.account_email ?? `Compte #${item.email_account_id}`}</span>
        </div>
        <StatusPill value={item.status} />
      </div>
      <p>{item.snippet ?? "Aucun extrait disponible."}</p>
      <div className="relance-meta">
        <span>{item.from_email ?? "expediteur inconnu"}</span>
        <span>Thread {item.gmail_thread_id}</span>
        <span>{formatDateTime(item.processed_at ?? item.updated_at)}</span>
      </div>
      {item.reason ? <small className="relance-note">{formatReason(item.reason)}</small> : null}
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

function OrderLine({ order }: { order: GmailRelanceOrderSummary | null }) {
  if (!order) {
    return <p className="relance-order relance-order--missing">Dossier non rattache pour l'instant.</p>;
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
  const tone = ["sent", "accepted", "payment_to_verify", "payment_confirmed", "linked", "positive"].includes(value)
    ? "positive"
    : ["skipped", "failed", "manual_review", "refused", "evidence_needed", "unlinked"].includes(value)
      ? "warning"
      : "neutral";
  return <span className={`status-pill status-pill--${tone}`}>{formatStatus(value)}</span>;
}

function formatStatus(value: string): string {
  const labels: Record<string, string> = {
    active: "surveille",
    accepted: "positif",
    evidence_needed: "preuve demandee",
    failed: "erreur",
    linked: "rattache",
    manual_review: "a verifier",
    payment_confirmed: "paiement confirme",
    payment_to_verify: "paiement a verifier",
    pending: "en attente",
    positive: "positif",
    processed: "traite",
    provider_draft_created: "brouillon Gmail",
    refused: "refus",
    send_requested: "envoi demande",
    sent: "envoye",
    skipped: "bloque",
    unlinked: "non rattache",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function formatReason(value: string): string {
  const labels: Record<string, string> = {
    evidence_requested: "Uber demande une preuve.",
    manual_review_required: "TENNET ne peut pas agir proprement sans verification.",
    payment_positive: "Paiement positif detecte.",
    refused_response: "Refus Uber detecte, le thread reste surveille.",
    thread_message_processed: "Message traite dans le thread surveille.",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}
