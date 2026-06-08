"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  formatDate,
  type ClaimOrder,
  type GmailInboundStatus,
  type GmailInboundSyncResponse,
  type InboundEmailMatchStatus,
  type InboundEmailMessage,
} from "@/lib/api";

type FilterValue = InboundEmailMatchStatus | "";

export default function InboxPage() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<InboundEmailMessage[]>([]);
  const [orders, setOrders] = useState<ClaimOrder[]>([]);
  const [status, setStatus] = useState<GmailInboundStatus | null>(null);
  const [syncResult, setSyncResult] = useState<GmailInboundSyncResponse | null>(null);
  const [filter, setFilter] = useState<FilterValue>("");
  const [linkSelections, setLinkSelections] = useState<Record<number, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [linkingMessageId, setLinkingMessageId] = useState<number | null>(null);

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
      const result = await api.syncInboundGmail({ lookback_days: 30, max_messages: 100 });
      setSyncResult(result);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSyncing(false);
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
          <button type="button" className="button" onClick={handleSync} disabled={syncing || !status?.enabled}>
            {syncing ? "Synchronisation" : "Synchroniser les reponses Gmail"}
          </button>
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
        <p className="muted">Lecture et rattachement uniquement. Aucune reponse automatique n'est envoyee.</p>
        {syncResult ? (
          <div className="success-box">
            <strong>Synchronisation terminee</strong>
            <span>
              {syncResult.synced_messages} message(s), {syncResult.linked_messages} rattache(s),{" "}
              {syncResult.unlinked_messages} non rattache(s), {syncResult.ignored_messages} ignore(s)
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
                <th>Commande</th>
                <th>Rattacher</th>
              </tr>
            </thead>
            <tbody>
              {messages.map((message) => (
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
                    ) : (
                      "-"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune reponse Gmail" />
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
