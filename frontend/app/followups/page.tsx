"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type FollowUpRecalculateResponse,
  type FollowUpTaskStatus,
  type FollowUpTaskSummary,
  type FollowUpTaskType,
  type Restaurant,
} from "@/lib/api";

type StatusFilter = FollowUpTaskStatus | "";
type TypeFilter = FollowUpTaskType | "";

const taskTypes: FollowUpTaskType[] = ["followup_1", "followup_2", "escalation", "manual_review", "payment_verification"];
const taskStatuses: FollowUpTaskStatus[] = [
  "pending",
  "draft_created",
  "provider_draft_created",
  "completed",
  "skipped",
  "cancelled",
];

export default function FollowUpsPage() {
  const [tasks, setTasks] = useState<FollowUpTaskSummary[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantFilter, setRestaurantFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("");
  const [skipReasons, setSkipReasons] = useState<Record<number, string>>({});
  const [recalculateResult, setRecalculateResult] = useState<FollowUpRecalculateResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [actionTaskId, setActionTaskId] = useState<number | null>(null);
  const [recalculating, setRecalculating] = useState(false);

  const loadData = useCallback(async () => {
    const restaurantId = restaurantFilter ? Number(restaurantFilter) : undefined;
    const [tasksData, restaurantsData] = await Promise.all([
      api.getDueFollowups({
        restaurant_id: restaurantId,
        status: statusFilter,
        task_type: typeFilter,
        limit: 200,
      }),
      api.getRestaurants(),
    ]);
    setTasks(tasksData.tasks);
    setRestaurants(restaurantsData);
  }, [restaurantFilter, statusFilter, typeFilter]);

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
      const result = await api.recalculateFollowups({
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

  async function runTaskAction(taskId: number, action: "draft" | "gmail" | "skip" | "complete") {
    setActionTaskId(taskId);
    setActionError(null);

    try {
      if (action === "draft") {
        await api.createFollowupDraft(taskId);
      } else if (action === "gmail") {
        await api.createFollowupGmailDraft(taskId);
      } else if (action === "skip") {
        const skipReason = skipReasons[taskId]?.trim();
        if (!skipReason) {
          throw new Error("Renseignez une raison pour ignorer la relance.");
        }
        await api.skipFollowupTask(taskId, { skip_reason: skipReason });
      } else {
        await api.completeFollowupTask(taskId);
      }
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setActionTaskId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des relances" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Relances</p>
          <h1>Workflow controle</h1>
        </div>
        <button type="button" className="button" onClick={handleRecalculate} disabled={recalculating}>
          {recalculating ? "Recalcul" : "Recalculer les relances"}
        </button>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Regles V1</h2>
          <StatusBadge status="manual_review" />
        </div>
        <div className="detail-grid">
          <DetailItem label="Email automatique" value="Jamais" />
          <DetailItem label="Relances" value="Limitees et tracables" />
          <DetailItem label="Envoi Gmail" value="Confirmation manuelle requise" />
        </div>
        {recalculateResult ? (
          <div className="success-box">
            <strong>Recalcul termine</strong>
            <span>
              {recalculateResult.created_tasks} creee(s), {recalculateResult.skipped_orders} ignoree(s),{" "}
              {recalculateResult.manual_review_orders} revue(s) manuelle(s)
            </span>
          </div>
        ) : null}
      </section>

      <section className="tool-panel">
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
            <label htmlFor="status_filter">Statut tache</label>
            <select id="status_filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="">Tous</option>
              {taskStatuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="type_filter">Type</label>
            <select id="type_filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}>
              <option value="">Tous</option>
              {taskTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {tasks.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Commande</th>
                <th>Statut dossier</th>
                <th>Type</th>
                <th>Echeance</th>
                <th>Statut</th>
                <th>Montant</th>
                <th>Actions</th>
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
                    <StatusBadge status={task.claim_status} />
                  </td>
                  <td>
                    <StatusBadge status={task.task_type} />
                  </td>
                  <td>{formatDate(task.due_at)}</td>
                  <td>
                    <StatusBadge status={task.status} />
                  </td>
                  <td>{formatCurrency(task.order_amount, task.currency)}</td>
                  <td>
                    <div className="inline-form">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => runTaskAction(task.id, "draft")}
                        disabled={task.status !== "pending" || actionTaskId === task.id}
                      >
                        Brouillon interne
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => runTaskAction(task.id, "gmail")}
                        disabled={task.status !== "draft_created" || actionTaskId === task.id}
                      >
                        Brouillon Gmail
                      </button>
                      <button
                        type="button"
                        className="button"
                        onClick={() => runTaskAction(task.id, "complete")}
                        disabled={["completed", "skipped", "cancelled"].includes(task.status) || actionTaskId === task.id}
                      >
                        Terminer
                      </button>
                      <input
                        aria-label={`Raison ignore relance ${task.id}`}
                        placeholder="Raison skip"
                        value={skipReasons[task.id] ?? ""}
                        onChange={(event) => setSkipReasons((current) => ({ ...current, [task.id]: event.target.value }))}
                      />
                      <button
                        type="button"
                        className="danger-button"
                        onClick={() => runTaskAction(task.id, "skip")}
                        disabled={task.status === "completed" || actionTaskId === task.id}
                      >
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
        <EmptyState title="Aucune relance" />
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
