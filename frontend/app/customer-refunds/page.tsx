"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type CustomerRefundDetectResponse,
  type CustomerRefundDisputeStatus,
  type CustomerRefundDisputeSummary,
  type CustomerRefundDisputeType,
  type CustomerRefundEvidenceStatus,
  type Restaurant,
} from "@/lib/api";

const disputeTypes: Array<CustomerRefundDisputeType | ""> = [
  "",
  "order_not_received",
  "missing_item",
  "incorrect_item",
  "damaged_order",
  "quality_issue",
  "customer_refund",
  "order_error_adjustment",
  "chargeback",
  "unknown",
];

const statuses: Array<CustomerRefundDisputeStatus | ""> = [
  "",
  "needs_evidence",
  "evidence_ready",
  "draft_created",
  "gmail_draft_created",
  "sent",
  "accepted",
  "payment_to_verify",
  "payment_confirmed",
  "refused",
  "ignored",
  "manual_review",
];

const evidenceStatuses: Array<CustomerRefundEvidenceStatus | ""> = ["", "missing", "partial", "complete", "manual_review"];

export default function CustomerRefundsPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [disputes, setDisputes] = useState<CustomerRefundDisputeSummary[]>([]);
  const [restaurantId, setRestaurantId] = useState("");
  const [disputeType, setDisputeType] = useState<CustomerRefundDisputeType | "">("");
  const [statusFilter, setStatusFilter] = useState<CustomerRefundDisputeStatus | "">("");
  const [evidenceFilter, setEvidenceFilter] = useState<CustomerRefundEvidenceStatus | "">("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [detectResult, setDetectResult] = useState<CustomerRefundDetectResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);
  const [workingId, setWorkingId] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    const filters = {
      restaurant_id: restaurantId ? Number(restaurantId) : ("" as const),
      dispute_type: disputeType,
      status: statusFilter,
      evidence_status: evidenceFilter,
      date_from: dateFrom,
      date_to: dateTo,
      limit: 200,
    };
    const [restaurantData, disputeData] = await Promise.all([
      api.getRestaurants(),
      api.getCustomerRefundDisputes(filters),
    ]);
    setRestaurants(restaurantData);
    setDisputes(disputeData.disputes);
  }, [dateFrom, dateTo, disputeType, evidenceFilter, restaurantId, statusFilter]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleDetect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setDetecting(true);
    setActionError(null);
    setDetectResult(null);

    try {
      const result = await api.detectCustomerRefundDisputes({
        restaurant_id: restaurantId ? Number(restaurantId) : null,
        date_from: dateFrom || null,
        date_to: dateTo || null,
      });
      setDetectResult(result);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDetecting(false);
    }
  }

  async function handleCreateClaim(disputeId: number) {
    setWorkingId(disputeId);
    setActionError(null);
    try {
      await api.createClaimOrderFromCustomerRefund(disputeId);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setWorkingId(null);
    }
  }

  async function handleIgnore(disputeId: number) {
    setWorkingId(disputeId);
    setActionError(null);
    try {
      await api.ignoreCustomerRefundDispute(disputeId, { reason: "Ignore depuis la liste deductions Uber" });
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setWorkingId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement deductions Uber" />;
  }

  const totalDeducted = disputes.reduce((sum, dispute) => sum + Number(dispute.customer_refund_amount ?? 0), 0);
  const needsEvidenceCount = disputes.filter((dispute) => dispute.evidence_status === "missing" || dispute.evidence_status === "partial").length;
  const readyCount = disputes.filter((dispute) => dispute.evidence_status === "complete").length;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Deductions Uber</h1>
          <p>Aucune contestation et aucun email ne sont envoyes automatiquement.</p>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <div className="stats-grid">
        <StatCard label="Total deduit" value={formatCurrency(totalDeducted)} />
        <StatCard label="Disputes detectees" value={disputes.length} />
        <StatCard label="Preuves manquantes" value={needsEvidenceCount} />
        <StatCard label="Pretes a contester" value={readyCount} />
        <StatCard label="Envoyees" value={disputes.filter((dispute) => dispute.status === "sent").length} />
        <StatCard label="Acceptees" value={disputes.filter((dispute) => dispute.status === "accepted").length} />
        <StatCard label="Refusees" value={disputes.filter((dispute) => dispute.status === "refused").length} />
      </div>

      <form className="tool-panel" onSubmit={handleDetect}>
        <div className="section-heading">
          <h2>Detection controlee</h2>
          <span className="muted">Analyse les transactions Uber importees. Aucun scraping, aucun mot de passe Uber.</span>
        </div>
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select id="restaurant_id" value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)}>
              <option value="">Tous accessibles</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="date_from">Depuis</label>
            <input id="date_from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="date_to">Jusqu'au</label>
            <input id="date_to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="type_filter">Type</label>
            <select id="type_filter" value={disputeType} onChange={(event) => setDisputeType(event.target.value as CustomerRefundDisputeType | "")}>
              {disputeTypes.map((type) => (
                <option key={type || "all"} value={type}>
                  {type || "Tous types"}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="status_filter">Statut</label>
            <select id="status_filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as CustomerRefundDisputeStatus | "")}>
              {statuses.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "Tous statuts"}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="evidence_filter">Preuves</label>
            <select id="evidence_filter" value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as CustomerRefundEvidenceStatus | "")}>
              {evidenceStatuses.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "Tous etats"}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={detecting}>
            {detecting ? "Detection" : "Detecter deductions"}
          </button>
          <button type="button" className="secondary-button" onClick={() => void loadData()}>
            Appliquer filtres
          </button>
        </div>
        {detectResult ? (
          <div className="success-box">
            <strong>Detection terminee</strong>
            <span>
              {detectResult.detected_count} creee(s), {detectResult.needs_evidence_count} avec preuves manquantes,{" "}
              {detectResult.manual_review_count} en revue manuelle.
            </span>
            <span>Montant deduit: {formatCurrency(detectResult.total_deducted_amount)}</span>
          </div>
        ) : null}
      </form>

      {disputes.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Commande</th>
                <th>Type</th>
                <th>Raison</th>
                <th>Montant deduit</th>
                <th>Statut</th>
                <th>Preuves</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {disputes.map((dispute) => (
                <tr key={dispute.id}>
                  <td>{dispute.restaurant_name}</td>
                  <td>{dispute.display_id || dispute.uber_order_id || "-"}</td>
                  <td>{dispute.dispute_type}</td>
                  <td>{dispute.reason}</td>
                  <td>{formatCurrency(dispute.customer_refund_amount, dispute.currency)}</td>
                  <td>
                    <StatusBadge status={dispute.status} />
                  </td>
                  <td>
                    <div className="stack-sm">
                      <StatusBadge status={dispute.evidence_status} />
                      <span className="muted">
                        {dispute.pending_requirements_count}/{dispute.requirements_count} en attente
                      </span>
                    </div>
                  </td>
                  <td>
                    <div className="actions">
                      <Link className="secondary-button" href={`/customer-refunds/${dispute.id}`}>
                        Detail
                      </Link>
                      {dispute.claim_order_id ? (
                        <Link className="secondary-button" href={`/orders/${dispute.claim_order_id}`}>
                          Dossier
                        </Link>
                      ) : (
                        <button type="button" className="button" disabled={workingId === dispute.id} onClick={() => handleCreateClaim(dispute.id)}>
                          Creer dossier
                        </button>
                      )}
                      <button type="button" className="danger-button" disabled={workingId === dispute.id || dispute.status === "ignored"} onClick={() => handleIgnore(dispute.id)}>
                        Ignorer
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune deduction detectee" />
      )}
    </section>
  );
}
