"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  formatDate,
  type ClaimResponseReview,
  type ClaimResponseReviewCreatePayload,
  type ClaimResponseReviewType,
  type ClaimOrder,
  type GmailInboundStatus,
  type GmailInboundSyncResponse,
  type GmailResponseAnalysis,
  type GmailResponseAnalyzeResponse,
  type InboundEmailMatchStatus,
  type InboundEmailMessage,
} from "@/lib/api";

type FilterValue = InboundEmailMatchStatus | "";
type ReviewForm = {
  review_type: ClaimResponseReviewType;
  recovered_amount: string;
  expected_payment_date: string;
  refusal_reason: string;
  notes: string;
};

const reviewTypes: ClaimResponseReviewType[] = [
  "accepted",
  "payment_to_verify",
  "payment_confirmed",
  "refused",
  "evidence_requested",
  "information_requested",
  "followup_needed",
  "ignored",
  "manual_review",
];

const initialReviewForm: ReviewForm = {
  review_type: "manual_review",
  recovered_amount: "",
  expected_payment_date: "",
  refusal_reason: "",
  notes: "",
};

export default function InboxPage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<InboundEmailMessage[]>([]);
  const [orders, setOrders] = useState<ClaimOrder[]>([]);
  const [status, setStatus] = useState<GmailInboundStatus | null>(null);
  const [syncResult, setSyncResult] = useState<GmailInboundSyncResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<GmailResponseAnalyzeResponse | null>(null);
  const [reviewResult, setReviewResult] = useState<ClaimResponseReview | null>(null);
  const [filter, setFilter] = useState<FilterValue>("");
  const [linkSelections, setLinkSelections] = useState<Record<number, string>>({});
  const [reviewForms, setReviewForms] = useState<Record<number, ReviewForm>>({});
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzingMessageId, setAnalyzingMessageId] = useState<number | null>(null);
  const [linkingMessageId, setLinkingMessageId] = useState<number | null>(null);
  const [reviewingMessageId, setReviewingMessageId] = useState<number | null>(null);

  const canSync = user?.role === "owner" || user?.role === "manager";

  const loadData = useCallback(async () => {
    const [messagesData, ordersData, statusData] = await Promise.all([
      api.getInboundMessages({ match_status: filter, limit: 100 }),
      api.getOrders(),
      canSync ? api.getInboundStatus() : Promise.resolve(null),
    ]);
    setMessages(messagesData.messages);
    setOrders(ordersData);
    setStatus(statusData);
  }, [canSync, filter]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleSync() {
    setSyncing(true);
    setActionError(null);
    setSyncResult(null);

    try {
      const result = await api.syncInboundGmail({
        lookback_days: 30,
        max_messages: 100,
        analyze_responses: true,
        apply_reviews: true,
        run_autopilot_after_sync: true,
      });
      setSyncResult(result);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSyncing(false);
    }
  }

  async function handleAnalyzeInbox() {
    setAnalyzing(true);
    setActionError(null);
    setAnalysisResult(null);

    try {
      const result = await api.analyzeInboundGmail({ apply_reviews: true, limit: 100, only_unreviewed: true });
      setAnalysisResult(result);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleAnalyzeMessage(messageId: number) {
    setAnalyzingMessageId(messageId);
    setActionError(null);
    try {
      await api.analyzeInboundMessage(messageId, { apply_reviews: true });
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setAnalyzingMessageId(null);
    }
  }

  async function handleLink(messageId: number) {
    const selectedOrderId = Number(linkSelections[messageId]);
    if (!Number.isFinite(selectedOrderId)) {
      setActionError(new Error("Selectionnez une commande a rattacher."));
      return;
    }
    setLinkingMessageId(messageId);
    setActionError(null);

    try {
      await api.linkInboundMessage(messageId, selectedOrderId);
      setLinkSelections((current) => ({ ...current, [messageId]: "" }));
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setLinkingMessageId(null);
    }
  }

  function getReviewForm(messageId: number): ReviewForm {
    return reviewForms[messageId] ?? initialReviewForm;
  }

  function updateReviewForm(messageId: number, patch: Partial<ReviewForm>) {
    setReviewForms((current) => ({
      ...current,
      [messageId]: {
        ...getReviewForm(messageId),
        ...patch,
      },
    }));
  }

  async function handleReview(event: FormEvent<HTMLFormElement>, message: InboundEmailMessage) {
    event.preventDefault();
    if (!message.order_id) {
      setActionError(new Error("Rattachez ce message a une commande avant de le traiter."));
      return;
    }

    const form = getReviewForm(message.id);
    const payload: ClaimResponseReviewCreatePayload = {
      inbound_message_id: message.id,
      review_type: form.review_type,
      recovered_amount: form.recovered_amount.trim() || null,
      expected_payment_date: form.expected_payment_date || null,
      refusal_reason: form.refusal_reason.trim() || null,
      evidence_requested: form.review_type === "evidence_requested" ? true : null,
      notes: form.notes.trim() || null,
    };

    setReviewingMessageId(message.id);
    setActionError(null);
    setReviewResult(null);

    try {
      const result = await api.createResponseReview(message.order_id, payload);
      setReviewResult(result);
      setReviewForms((current) => ({ ...current, [message.id]: initialReviewForm }));
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setReviewingMessageId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des reponses Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Reponses Uber</p>
          <h1>Inbox Gmail</h1>
        </div>
        {canSync ? (
          <div className="button-row">
            <button type="button" className="button" onClick={handleSync} disabled={syncing || !status?.enabled}>
              {syncing ? "Synchronisation" : "Synchroniser et traiter"}
            </button>
            <button type="button" className="secondary-button" onClick={handleAnalyzeInbox} disabled={analyzing}>
              {analyzing ? "Analyse" : "Analyser les reponses liees"}
            </button>
          </div>
        ) : null}
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Etat sync</h2>
          <StatusBadge status={!status?.enabled ? "disabled" : status.status ?? "idle"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Lecture Gmail" value={!status?.enabled ? "desactivee" : "activee"} />
          <DetailItem label="Compte" value={status?.connected ? "connecte" : "non connecte"} />
          <DetailItem label="Dernier succes" value={formatDate(status?.last_success_at ?? null)} />
        </div>
        <p className="muted">
          TENNET traite les reponses liees. AutoPilot envoie uniquement si Gmail, AutoPilot et le restaurant sont
          explicitement actives.
        </p>
        {syncResult ? (
          <div className="success-box">
            <strong>Synchronisation terminee</strong>
            <span>
              {syncResult.synced_messages} message(s), {syncResult.linked_messages} rattache(s),{" "}
              {syncResult.unlinked_messages} non rattache(s), {syncResult.ignored_messages} ignore(s),{" "}
              {syncResult.applied_reviews} decision(s) appliquee(s), {syncResult.manual_review_messages} a verifier
            </span>
            {syncResult.negative_responses_detected > 0 ? (
              <span>
                Reponses negatives: {syncResult.negative_responses_detected}. AutoPilot:{" "}
                {syncResult.autopilot_sent_count} envoyee(s), {syncResult.autopilot_skipped_count} a exploiter,{" "}
                {syncResult.autopilot_failed_count} erreur(s).
              </span>
            ) : null}
          </div>
        ) : null}
        {analysisResult ? (
          <div className="success-box">
            <strong>Analyse terminee</strong>
            <span>
              {analysisResult.applied_reviews} decision(s) appliquee(s), {analysisResult.manual_review_messages} a
              verifier, {analysisResult.failed_messages} erreur(s)
            </span>
          </div>
        ) : null}
        {reviewResult ? (
          <div className="success-box">
            <strong>Traitement enregistre</strong>
            <span>
              Commande #{reviewResult.order_id}: {reviewResult.previous_order_status} vers{" "}
              {reviewResult.new_order_status}
            </span>
          </div>
        ) : null}
      </section>

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="match_filter">Filtre statut</label>
            <select id="match_filter" value={filter} onChange={(event) => setFilter(event.target.value as FilterValue)}>
              <option value="">Tous</option>
              <option value="linked">linked</option>
              <option value="unlinked">unlinked</option>
              <option value="ignored">ignored</option>
            </select>
          </div>
        </div>
      </section>

      {messages.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>De</th>
                <th>Sujet</th>
                <th>Extrait</th>
                <th>Reception</th>
                <th>Match</th>
                <th>Decision TENNET</th>
                <th>Revue</th>
                <th>Commande</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((message) => {
                const reviewForm = getReviewForm(message.id);
                return (
                  <tr key={message.id}>
                    <td>{message.from_email ?? "-"}</td>
                    <td>{message.subject ?? "-"}</td>
                    <td>{message.snippet ?? "-"}</td>
                    <td>{formatDate(message.received_at)}</td>
                    <td>
                      <div className="stack-sm">
                        <StatusBadge status={message.match_status} />
                        <span className="muted">{message.match_reason}</span>
                      </div>
                    </td>
                    <td>
                      <AnalysisSummary analysis={message.response_analysis} />
                    </td>
                    <td>
                      <div className="stack-sm">
                        <StatusBadge status={message.review_status} />
                        <span className="muted">{formatDate(message.reviewed_at)}</span>
                      </div>
                    </td>
                    <td>
                      {message.order_id ? (
                        <Link href={`/orders/${message.order_id}`} className="secondary-button">
                          Commande #{message.order_id}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>
                      {message.match_status === "unlinked" && canSync ? (
                        <div className="inline-form">
                          <select
                            aria-label={`Commande a rattacher message ${message.id}`}
                            value={linkSelections[message.id] ?? ""}
                            onChange={(event) =>
                              setLinkSelections((current) => ({ ...current, [message.id]: event.target.value }))
                            }
                          >
                            <option value="">Selection commande</option>
                            {orders.map((order) => (
                              <option key={order.id} value={order.id}>
                                #{order.id} - {order.uber_order_number}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="button"
                            onClick={() => handleLink(message.id)}
                            disabled={linkingMessageId === message.id}
                          >
                            {linkingMessageId === message.id ? "Rattachement" : "Rattacher"}
                          </button>
                        </div>
                      ) : null}
                      {message.match_status === "linked" && message.order_id && canSync ? (
                        <div className="stack-sm">
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => handleAnalyzeMessage(message.id)}
                            disabled={analyzingMessageId === message.id || message.review_status === "reviewed"}
                          >
                            {analyzingMessageId === message.id ? "Analyse" : "Analyser et traiter"}
                          </button>
                        <form className="inline-form" onSubmit={(event) => handleReview(event, message)}>
                          <select
                            aria-label={`Type traitement message ${message.id}`}
                            value={reviewForm.review_type}
                            onChange={(event) =>
                              updateReviewForm(message.id, {
                                review_type: event.target.value as ClaimResponseReviewType,
                              })
                            }
                          >
                            {reviewTypes.map((type) => (
                              <option key={type} value={type}>
                                {type}
                              </option>
                            ))}
                          </select>
                          <input
                            aria-label={`Montant recupere message ${message.id}`}
                            inputMode="decimal"
                            placeholder="Montant recupere"
                            value={reviewForm.recovered_amount}
                            onChange={(event) => updateReviewForm(message.id, { recovered_amount: event.target.value })}
                          />
                          <input
                            aria-label={`Date paiement attendu message ${message.id}`}
                            type="date"
                            value={reviewForm.expected_payment_date}
                            onChange={(event) =>
                              updateReviewForm(message.id, { expected_payment_date: event.target.value })
                            }
                          />
                          <input
                            aria-label={`Motif refus message ${message.id}`}
                            placeholder="Motif refus"
                            value={reviewForm.refusal_reason}
                            onChange={(event) => updateReviewForm(message.id, { refusal_reason: event.target.value })}
                          />
                          <textarea
                            aria-label={`Notes traitement message ${message.id}`}
                            placeholder="Notes internes"
                            value={reviewForm.notes}
                            onChange={(event) => updateReviewForm(message.id, { notes: event.target.value })}
                          />
                          <button type="submit" className="button" disabled={reviewingMessageId === message.id}>
                            {reviewingMessageId === message.id ? "Traitement" : "Traiter la reponse"}
                          </button>
                        </form>
                        </div>
                      ) : null}
                      {message.match_status !== "unlinked" && !(message.match_status === "linked" && canSync) ? "-" : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune reponse Gmail" />
      )}
    </section>
  );
}

function AnalysisSummary({ analysis }: { analysis: GmailResponseAnalysis | null }) {
  if (!analysis) {
    return <span className="muted">Non analysee</span>;
  }
  return (
    <div className="stack-sm">
      <StatusBadge status={analysis.status} />
      <strong>{reviewTypeLabel(analysis.recommended_review_type)}</strong>
      <span className="muted">
        Confiance {analysis.confidence_score ?? "-"}
        {analysis.detected_amount ? ` · Montant ${analysis.detected_amount} EUR` : ""}
      </span>
      {analysis.reason ? <span className="muted">{analysis.reason}</span> : null}
    </div>
  );
}

function reviewTypeLabel(value: ClaimResponseReviewType) {
  const labels: Record<ClaimResponseReviewType, string> = {
    accepted: "Acceptée",
    payment_to_verify: "Paiement à vérifier",
    payment_confirmed: "Paiement confirmé",
    refused: "Refusée",
    evidence_requested: "Preuves demandées",
    information_requested: "Informations demandées",
    followup_needed: "Suivi nécessaire",
    ignored: "Ignorée",
    manual_review: "À vérifier",
  };
  return labels[value];
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
