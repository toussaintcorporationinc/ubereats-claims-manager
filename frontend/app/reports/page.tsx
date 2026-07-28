"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  type CommercialSummary,
  type ReportFilters,
  type Restaurant,
} from "@/lib/api";

type ReportFilterState = {
  restaurant_id: string;
  date_from: string;
  date_to: string;
};

const initialFilters: ReportFilterState = {
  restaurant_id: "",
  date_from: "",
  date_to: "",
};

export default function ReportsPage() {
  const [summary, setSummary] = useState<CommercialSummary | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<ReportFilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  const queryFilters = useMemo(() => toReportFilters(filters), [filters]);

  const loadData = useCallback(async () => {
    const [summaryData, restaurantsData] = await Promise.all([
      api.getCommercialSummary(queryFilters),
      api.getRestaurants(),
    ]);
    setSummary(summaryData);
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
      const blob = await api.downloadReport(path, queryFilters);
      saveBlob(blob, filename);
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des rapports" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Rapports</p>
          <h1>Reporting commercial</h1>
        </div>
        <div className="actions">
          <Link href="/reports/orders" className="secondary-button">
            Commandes
          </Link>
          <Link href="/reports/followups" className="secondary-button">
            Relances
          </Link>
          <Link href="/reports/responses" className="secondary-button">
            Reponses
          </Link>
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
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={() => void loadData()}>
            Appliquer
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => setFilters(initialFilters)}
          >
            Reinitialiser
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "ubereats_claims_commercial_summary.xlsx"}
            onClick={() =>
              handleDownload("/v1/reports/export/commercial-summary.xlsx", "ubereats_claims_commercial_summary.xlsx")
            }
          >
            Export resume XLSX
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "ubereats_claims_orders.csv"}
            onClick={() => handleDownload("/v1/reports/export/orders.csv", "ubereats_claims_orders.csv")}
          >
            Export commandes CSV
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "ubereats_claims_orders.xlsx"}
            onClick={() => handleDownload("/v1/reports/export/orders.xlsx", "ubereats_claims_orders.xlsx")}
          >
            Export commandes XLSX
          </button>
        </div>
      </section>

      {summary ? (
        <>
          <div className="stats-grid">
            <StatCard label="Montant reclame" value={formatCurrency(summary.totals.total_claimed_amount)} />
            <StatCard label="Montant recupere" value={formatCurrency(summary.totals.total_recovered_amount)} />
            <StatCard label="Montant en attente" value={formatCurrency(summary.totals.total_pending_amount)} />
            <StatCard label="Montant refuse" value={formatCurrency(summary.totals.total_refused_amount)} />
            <StatCard label="Taux de reussite" value={formatPercent(summary.totals.success_rate)} />
            <StatCard label="Dossiers" value={summary.totals.orders_count} />
            <StatCard label="Relances dues" value={summary.followups.due_count} />
            <StatCard label="Relances en attente" value={summary.followups.pending_count} />
            <StatCard label="Escalades dues" value={summary.followups.escalation_due_count} />
            <StatCard label="Revues manuelles" value={summary.responses.manual_review_count} />
            <StatCard label="Deductions Uber" value={formatCurrency(summary.customer_refunds.total_deducted_amount)} />
            <StatCard label="Deductions recuperees" value={formatCurrency(summary.customer_refunds.total_recovered_amount)} />
            <StatCard
              label="Deductions accordees"
              value={formatCurrency(summary.customer_refunds.total_approved_amount)}
            />
            <StatCard label="Deductions en attente" value={formatCurrency(summary.customer_refunds.total_pending_amount)} />
            <StatCard label="Deductions refusees" value={formatCurrency(summary.customer_refunds.total_refused_amount)} />
            <StatCard label="Disputes deductions" value={summary.customer_refunds.disputes_count} />
            <StatCard label="Deductions besoin preuve" value={summary.customer_refunds.needs_evidence_count} />
            <StatCard label="Deductions pretes" value={summary.customer_refunds.evidence_ready_count} />
          </div>

          <div className="grid-two">
            <section className="tool-panel">
              <h2>Par restaurant</h2>
              {summary.by_restaurant.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Restaurant</th>
                        <th>Dossiers</th>
                        <th>Reclame</th>
                        <th>Recupere</th>
                        <th>En attente</th>
                        <th>Refuse</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.by_restaurant.map((restaurant) => (
                        <tr key={restaurant.restaurant_id}>
                          <td>{restaurant.restaurant_name}</td>
                          <td>{restaurant.orders_count}</td>
                          <td>{formatCurrency(restaurant.claimed_amount)}</td>
                          <td>{formatCurrency(restaurant.recovered_amount)}</td>
                          <td>{formatCurrency(restaurant.pending_amount)}</td>
                          <td>{formatCurrency(restaurant.refused_amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Aucun restaurant" />
              )}
            </section>

            <section className="tool-panel">
              <h2>Par statut</h2>
              <BreakdownTable rows={summary.by_status} />
            </section>
          </div>

          <section className="tool-panel">
            <h2>Par resultat</h2>
            <BreakdownTable rows={summary.by_result} />
          </section>
        </>
      ) : null}
    </section>
  );
}

function BreakdownTable({ rows }: { rows: CommercialSummary["by_status"] }) {
  if (rows.length === 0) {
    return <EmptyState title="Aucune donnee" />;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Cle</th>
            <th>Dossiers</th>
            <th>Reclame</th>
            <th>Recupere</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <StatusBadge status={row.key} />
              </td>
              <td>{row.count}</td>
              <td>{formatCurrency(row.claimed_amount)}</td>
              <td>{formatCurrency(row.recovered_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function toReportFilters(filters: ReportFilterState): ReportFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    date_from: filters.date_from,
    date_to: filters.date_to,
  };
}

function formatPercent(value: string | number | null): string {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(numericValue * 100)} %`;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}
