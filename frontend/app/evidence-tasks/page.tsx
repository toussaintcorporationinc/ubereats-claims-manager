"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import EvidenceTaskCard from "@/components/EvidenceTaskCard";
import LoadingState from "@/components/LoadingState";
import ResponsiveDataList from "@/components/ResponsiveDataList";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type EvidenceRequestPriority,
  type EvidenceRequestRecalculateResponse,
  type EvidenceRequestTaskStatus,
  type EvidenceRequestTaskSummary,
  type EvidenceType,
  type Restaurant,
} from "@/lib/api";

const evidenceTypes: EvidenceType[] = [
  "receipt",
  "cancellation_proof",
  "preparation_proof",
  "waste_photo",
  "uber_screenshot",
  "delivery_proof",
  "packaging_photo",
  "sealed_bag_photo",
  "courier_statement",
  "gps_or_route_proof",
  "customer_contact_proof",
  "order_details_screenshot",
  "other",
];
const statuses: EvidenceRequestTaskStatus[] = ["pending", "uploaded", "completed", "skipped", "cancelled"];
const priorities: EvidenceRequestPriority[] = ["low", "normal", "high", "urgent"];

export default function EvidenceTasksPage() {
  const [tasks, setTasks] = useState<EvidenceRequestTaskSummary[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantFilter, setRestaurantFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<EvidenceRequestTaskStatus | "">("pending");
  const [typeFilter, setTypeFilter] = useState<EvidenceType | "">("");
  const [priorityFilter, setPriorityFilter] = useState<EvidenceRequestPriority | "">("");
  const [recalculateResult, setRecalculateResult] = useState<EvidenceRequestRecalculateResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [recalculating, setRecalculating] = useState(false);

  const loadData = useCallback(async () => {
    const restaurantId = restaurantFilter ? Number(restaurantFilter) : undefined;
    const [tasksData, restaurantsData] = await Promise.all([
      api.getEvidenceTasks({
        restaurant_id: restaurantId,
        status: statusFilter,
        required_evidence_type: typeFilter,
        priority: priorityFilter,
        limit: 200,
      }),
      api.getRestaurants(),
    ]);
    setTasks(tasksData.tasks);
    setRestaurants(restaurantsData);
  }, [priorityFilter, restaurantFilter, statusFilter, typeFilter]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleRecalculate() {
    setRecalculating(true);
    setActionError(null);
    setRecalculateResult(null);

    try {
      const result = await api.recalculateEvidenceTasks({
        restaurant_id: restaurantFilter ? Number(restaurantFilter) : null,
        dry_run: false,
      });
      setRecalculateResult(result);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setRecalculating(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des preuves a fournir" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuves</p>
          <h1>Preuves a fournir</h1>
        </div>
        <button type="button" className="button" onClick={handleRecalculate} disabled={recalculating}>
          {recalculating ? "Recalcul" : "Recalculer les preuves"}
        </button>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>File de collecte</h2>
          <span className="muted">Aucune preuve n'est inventee. Aucun email n'est envoye automatiquement.</span>
        </div>
        {recalculateResult ? (
          <div className="success-box">
            <strong>Recalcul termine</strong>
            <span>
              {recalculateResult.created_tasks} creee(s), {recalculateResult.existing_tasks} existante(s),{" "}
              {recalculateResult.completed_tasks} completee(s)
            </span>
          </div>
        ) : null}
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_filter">Restaurant</label>
            <select id="restaurant_filter" value={restaurantFilter} onChange={(event) => setRestaurantFilter(event.target.value)}>
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
            <select
              id="status_filter"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as EvidenceRequestTaskStatus | "")}
            >
              <option value="">Tous</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="type_filter">Type preuve</label>
            <select id="type_filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as EvidenceType | "")}>
              <option value="">Tous</option>
              {evidenceTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="priority_filter">Priorite</label>
            <select
              id="priority_filter"
              value={priorityFilter}
              onChange={(event) => setPriorityFilter(event.target.value as EvidenceRequestPriority | "")}
            >
              <option value="">Toutes</option>
              {priorities.map((priority) => (
                <option key={priority} value={priority}>
                  {priority}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <ResponsiveDataList
        items={tasks}
        empty={<EmptyState title="Aucune preuve a fournir" />}
        renderMobileCard={(task) => <EvidenceTaskCard key={task.id} task={task} />}
        desktop={
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Restaurant</th>
                  <th>Commande</th>
                  <th>Preuve</th>
                  <th>Priorite</th>
                  <th>Statut</th>
                  <th>Montant</th>
                  <th>Contexte</th>
                  <th>Echeance</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id}>
                    <td>{task.restaurant_name}</td>
                    <td>
                      <Link href={`/orders/${task.order_id}`} className="secondary-button">
                        {task.uber_order_number}
                      </Link>
                    </td>
                    <td>
                      <div className="stack-sm">
                        <strong>{task.title}</strong>
                        <span className="muted">{task.required_evidence_type}</span>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={task.priority} />
                    </td>
                    <td>
                      <StatusBadge status={task.status} />
                    </td>
                    <td>{formatCurrency(task.order_amount, task.currency)}</td>
                    <td>
                      {task.customer_refund_dispute_id ? (
                        <Link href={`/customer-refunds/${task.customer_refund_dispute_id}`} className="secondary-button">
                          Deduction
                        </Link>
                      ) : task.reconciliation_result_id ? (
                        <span className="muted">Reconciliation</span>
                      ) : (
                        <span className="muted">Dossier</span>
                      )}
                    </td>
                    <td>{formatDate(task.due_at)}</td>
                    <td>
                      <Link href={`/evidence-tasks/${task.id}`} className="button">
                        Ouvrir
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
      />
    </section>
  );
}
