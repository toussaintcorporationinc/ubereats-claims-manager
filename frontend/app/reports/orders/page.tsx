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
  type ClaimOrderStatus,
  type ReportFilters,
  type ReportOrderRow,
  type Restaurant,
} from "@/lib/api";

type OrdersFilterState = {
  restaurant_id: string;
  date_from: string;
  date_to: string;
  status: string;
  result: string;
  include_customer_names: boolean;
};

const initialFilters: OrdersFilterState = {
  restaurant_id: "",
  date_from: "",
  date_to: "",
  status: "",
  result: "",
  include_customer_names: false,
};

const statusOptions: ClaimOrderStatus[] = [
  "draft",
  "missing_evidence",
  "ready_to_send",
  "draft_email_created",
  "sent",
  "waiting_uber_response",
  "response_received",
  "followup_1_sent",
  "followup_2_sent",
  "escalation_sent",
  "accepted",
  "payment_to_verify",
  "payment_confirmed",
  "refused",
  "manual_review",
  "closed",
];

export default function ReportOrdersPage() {
  const [orders, setOrders] = useState<ReportOrderRow[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<OrdersFilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  const queryFilters = useMemo(() => ({ ...toReportFilters(filters), limit: 200 }), [filters]);

  const loadData = useCallback(async () => {
    const [ordersData, restaurantsData] = await Promise.all([
      api.getReportOrders(queryFilters),
      api.getRestaurants(),
    ]);
    setOrders(ordersData.orders);
    setRestaurants(restaurantsData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleDownload(path: string, filename: string) {
    setDownloading(filename);
    setActionError(null);
    try {
      const blob = await api.downloadReport(path, toReportFilters(filters));
      saveBlob(blob, filename);
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du rapport commandes" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Rapports</p>
          <h1>Commandes exportables</h1>
        </div>
        <div className="actions">
          <Link href="/reports" className="secondary-button">
            Retour rapports
          </Link>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "ubereats_claims_orders.csv"}
            onClick={() => handleDownload("/v1/reports/export/orders.csv", "ubereats_claims_orders.csv")}
          >
            Export CSV
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "ubereats_claims_orders.xlsx"}
            onClick={() => handleDownload("/v1/reports/export/orders.xlsx", "ubereats_claims_orders.xlsx")}
          >
            Export XLSX
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
            <label htmlFor="status">Statut</label>
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
          <div className="field">
            <label htmlFor="result">Resultat</label>
            <input
              id="result"
              value={filters.result}
              onChange={(event) => setFilters((current) => ({ ...current, result: event.target.value }))}
              placeholder="accepted, refused..."
            />
          </div>
          <div className="field">
            <label htmlFor="date_from">Depuis</label>
            <input
              id="date_from"
              type="date"
              value={filters.date_from}
              onChange={(event) => setFilters((current) => ({ ...current, date_from: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="date_to">Jusqu'au</label>
            <input
              id="date_to"
              type="date"
              value={filters.date_to}
              onChange={(event) => setFilters((current) => ({ ...current, date_to: event.target.value }))}
            />
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={filters.include_customer_names}
              onChange={(event) =>
                setFilters((current) => ({ ...current, include_customer_names: event.target.checked }))
              }
            />
            Inclure noms clients
          </label>
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

      {orders.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Numero Uber</th>
                {filters.include_customer_names ? <th>Client</th> : null}
                <th>Date</th>
                <th>Montant</th>
                <th>Statut</th>
                <th>Resultat</th>
                <th>Recupere</th>
                <th>Relances</th>
                <th>Preuves</th>
                <th>Messages</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.order_id}>
                  <td>{order.restaurant_name}</td>
                  <td>{order.uber_order_number}</td>
                  {filters.include_customer_names ? <td>{order.customer_name ?? "-"}</td> : null}
                  <td>{order.order_date ?? "-"}</td>
                  <td>{formatCurrency(order.order_amount, order.currency)}</td>
                  <td>
                    <StatusBadge status={order.status} />
                  </td>
                  <td>{order.result ?? "-"}</td>
                  <td>{formatCurrency(order.recovered_amount, order.currency)}</td>
                  <td>{order.retry_count}</td>
                  <td>{order.evidence_count}</td>
                  <td>{order.inbound_messages_count}</td>
                  <td>
                    <Link href={`/orders/${order.order_id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune commande dans ce rapport" />
      )}
    </section>
  );
}

function toReportFilters(filters: OrdersFilterState): ReportFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    date_from: filters.date_from,
    date_to: filters.date_to,
    status: filters.status,
    result: filters.result,
    include_customer_names: filters.include_customer_names,
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
