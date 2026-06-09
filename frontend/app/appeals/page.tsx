"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type AppealWorkflowStatus,
  type AppealWorkflowSummary,
  type Restaurant,
} from "@/lib/api";

const statuses: Array<AppealWorkflowStatus | ""> = [
  "",
  "appeal_needed",
  "evidence_needed",
  "draft_needed",
  "gmail_draft_needed",
  "appeal_sent",
  "escalated",
  "payment_to_verify",
  "payment_confirmed",
  "accepted",
  "paused",
  "manually_closed",
];

export default function AppealsPage() {
  const [workflows, setWorkflows] = useState<AppealWorkflowSummary[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantId, setRestaurantId] = useState("");
  const [statusFilter, setStatusFilter] = useState<AppealWorkflowStatus | "">("");
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  const loadData = useCallback(async () => {
    const [appealsData, restaurantData] = await Promise.all([
      api.getAppeals({ restaurant_id: restaurantId ? Number(restaurantId) : "", status: statusFilter, limit: 200 }),
      api.getRestaurants(),
    ]);
    setWorkflows(appealsData.workflows);
    setRestaurants(restaurantData);
  }, [restaurantId, statusFilter]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleRecalculate() {
    setWorking(true);
    setActionError(null);
    try {
      await api.recalculateAppeals({ restaurant_id: restaurantId ? Number(restaurantId) : null });
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement appels" />;
  }

  const due = workflows.filter((workflow) => workflow.next_action_type).length;
  const escalations = workflows.filter((workflow) => workflow.next_action_type === "escalation").length;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Appels</p>
          <h1>Appels / Refus Uber</h1>
          <p>TENNET ne cloture pas automatiquement un refus. Les appels restent controles, tracables et envoyes manuellement.</p>
        </div>
        <button type="button" className="button" disabled={working} onClick={handleRecalculate}>
          Recalculer
        </button>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <div className="stats-grid">
        <StatCard label="Workflows" value={workflows.length} />
        <StatCard label="Actions" value={due} />
        <StatCard label="Escalades" value={escalations} />
      </div>

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select id="restaurant_id" value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)}>
              <option value="">Tous</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="status_filter">Statut</label>
            <select id="status_filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AppealWorkflowStatus | "")}>
              {statuses.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "Tous"}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="tool-panel">
        <h2>Workflows</h2>
        {workflows.length === 0 ? (
          <EmptyState title="Aucun appel a traiter" />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Restaurant</th>
                  <th>Commande</th>
                  <th>Type</th>
                  <th>Montant</th>
                  <th>Refus</th>
                  <th>Appels</th>
                  <th>Action</th>
                  <th>Statut</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {workflows.map((workflow) => (
                  <tr key={workflow.id}>
                    <td>{workflow.restaurant_name}</td>
                    <td>{workflow.uber_order_number ?? "-"}</td>
                    <td>{workflow.case_type}</td>
                    <td>{formatCurrency(workflow.amount, workflow.currency)}</td>
                    <td>{workflow.refusal_count}</td>
                    <td>{workflow.appeal_attempt_count}</td>
                    <td>{workflow.next_action_type ?? "-"}</td>
                    <td>
                      <StatusBadge status={workflow.status} />
                    </td>
                    <td>
                      <Link href={`/appeals/${workflow.id}`} className="secondary-button">
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
