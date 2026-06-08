"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type ClaimOrderStatus,
  type ReportFilters,
  type ReportFollowupRow,
  type Restaurant,
} from "@/lib/api";

type FollowupsFilterState = {
  restaurant_id: string;
  status: string;
};

const initialFilters: FollowupsFilterState = {
  restaurant_id: "",
  status: "",
};

const statusOptions: ClaimOrderStatus[] = [
  "sent",
  "waiting_uber_response",
  "response_received",
  "followup_1_sent",
  "followup_2_sent",
  "escalation_sent",
  "manual_review",
];

export default function ReportFollowupsPage() {
  const [followups, setFollowups] = useState<ReportFollowupRow[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<FollowupsFilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const queryFilters = useMemo(() => ({ ...toReportFilters(filters), limit: 200 }), [filters]);

  const loadData = useCallback(async () => {
    const [followupsData, restaurantsData] = await Promise.all([
      api.getReportFollowups(queryFilters),
      api.getRestaurants(),
    ]);
    setFollowups(followupsData.followups);
    setRestaurants(restaurantsData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleDownload() {
    setDownloading(true);
    setActionError(null);
    try {
      const blob = await api.downloadReport("/v1/reports/export/followups.csv", toReportFilters(filters));
      saveBlob(blob, "ubereats_claims_followups.csv");
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du rapport relances" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Rapports</p>
          <h1>Relances</h1>
        </div>
        <div className="actions">
          <Link href="/reports" className="secondary-button">
            Retour rapports
          </Link>
          <button type="button" className="secondary-button" disabled={downloading} onClick={handleDownload}>
            Export CSV
          </button>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select
              id="restaurant_id"
              value={filters.restaurant_id}
              onChange={(event) => setFilters((current) => ({ ...current, restaurant_id: event.target.value }))}
            >
              <option value="">Tous</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="status">Statut dossier</label>
            <select
              id="status"
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
            >
              <option value="">Tous</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={() => void loadData()}>
            Appliquer
          </button>
          <button type="button" className="secondary-button" onClick={() => setFilters(initialFilters)}>
            Reinitialiser
          </button>
        </div>
      </section>

      {followups.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Commande</th>
                <th>Type relance</th>
                <th>Statut tache</th>
                <th>Echeance</th>
                <th>Montant</th>
                <th>Statut dossier</th>
                <th>Relances</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {followups.map((followup) => (
                <tr key={followup.task_id}>
                  <td>{followup.restaurant_name}</td>
                  <td>{followup.uber_order_number}</td>
                  <td>
                    <StatusBadge status={followup.task_type} />
                  </td>
                  <td>
                    <StatusBadge status={followup.task_status} />
                  </td>
                  <td>{formatDate(followup.due_at)}</td>
                  <td>{formatCurrency(followup.order_amount, followup.currency)}</td>
                  <td>
                    <StatusBadge status={followup.claim_status} />
                  </td>
                  <td>{followup.retry_count}</td>
                  <td>
                    <Link href={`/orders/${followup.order_id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune relance dans ce rapport" />
      )}
    </section>
  );
}

function toReportFilters(filters: FollowupsFilterState): ReportFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    status: filters.status,
  };
}

function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}
