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
  type RecoveryFilters,
  type RecoverySummary,
  type Restaurant,
} from "@/lib/api";

type FilterState = {
  restaurant_id: string;
  date_from: string;
  date_to: string;
};

const initialFilters: FilterState = { restaurant_id: "", date_from: "", date_to: "" };

export default function RecoveryPage() {
  const [summary, setSummary] = useState<RecoverySummary | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  const queryFilters = useMemo(() => toRecoveryFilters(filters), [filters]);

  const loadData = useCallback(async () => {
    const [summaryData, restaurantData] = await Promise.all([
      api.getRecoverySummary(queryFilters),
      api.getRestaurants(),
    ]);
    setSummary(summaryData);
    setRestaurants(restaurantData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleDownload(kind: "summary" | "cases") {
    const filename = kind === "summary" ? "tennet_recovery_summary.xlsx" : "tennet_recovery_cases.csv";
    setDownloading(filename);
    setActionError(null);
    try {
      const blob = kind === "summary" ? await api.downloadRecoverySummaryXlsx(queryFilters) : await api.downloadRecoveryCasesCsv(queryFilters);
      saveBlob(blob, filename);
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement cockpit recuperation" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Recuperation</p>
          <h1>Cockpit recuperation</h1>
          <p>TENNET ne garantit pas le remboursement. TENNET garantit le suivi et la revue systematique des pertes detectees.</p>
        </div>
        <div className="actions">
          <Link href="/recovery/cases" className="secondary-button">
            Cases
          </Link>
          <Link href="/recovery/actions" className="secondary-button">
            Actions
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
          <button type="button" className="secondary-button" onClick={() => setFilters(initialFilters)}>
            Reinitialiser
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "tennet_recovery_summary.xlsx"}
            onClick={() => handleDownload("summary")}
          >
            Export resume XLSX
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={downloading === "tennet_recovery_cases.csv"}
            onClick={() => handleDownload("cases")}
          >
            Export cases CSV
          </button>
        </div>
      </section>

      {summary ? (
        <>
          <div className="stats-grid">
            <StatCard label="Montant detecte" value={formatCurrency(summary.totals.detected_amount)} />
            <StatCard label="Contestable" value={formatCurrency(summary.totals.claimable_amount)} />
            <StatCard label="Attente preuve" value={formatCurrency(summary.totals.missing_evidence_amount)} />
            <StatCard label="Envoye" value={formatCurrency(summary.totals.sent_amount)} />
            <StatCard label="Recupere" value={formatCurrency(summary.totals.recovered_amount)} />
            <StatCard label="Refuse" value={formatCurrency(summary.totals.refused_amount)} />
            <StatCard label="En attente" value={formatCurrency(summary.totals.pending_amount)} />
            <StatCard label="Taux recuperation" value={formatPercent(summary.totals.recovery_rate)} />
            <StatCard label="Couverture revue" value={formatPercent(summary.totals.review_coverage_rate)} />
            <StatCard label="Revue manuelle" value={summary.totals.manual_review_count} />
          </div>

          <div className="grid-two">
            <section className="tool-panel">
              <h2>Par restaurant</h2>
              <BreakdownTable rows={summary.by_restaurant} labelKey="restaurant_name" />
            </section>
            <section className="tool-panel">
              <h2>Par categorie</h2>
              <BreakdownTable rows={summary.by_loss_category} />
            </section>
          </div>

          <section className="tool-panel">
            <h2>Par etape</h2>
            <BreakdownTable rows={summary.by_recovery_stage} badge />
          </section>

          <section className="tool-panel">
            <h2>Top dossiers recuperables</h2>
            {summary.top_recoverable_cases.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Restaurant</th>
                      <th>Commande</th>
                      <th>Categorie</th>
                      <th>Etape</th>
                      <th>Contestable</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.top_recoverable_cases.map((item) => (
                      <tr key={`${item.case_type}-${item.case_id}`}>
                        <td>{item.restaurant_name}</td>
                        <td>{item.uber_order_number ?? "-"}</td>
                        <td>{item.loss_category}</td>
                        <td>
                          <StatusBadge status={item.recovery_stage} />
                        </td>
                        <td>{formatCurrency(item.claimable_amount)}</td>
                        <td>
                          <Link className="secondary-button" href={item.link_url}>
                            Ouvrir
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="Aucun dossier recuperable" />
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}

function BreakdownTable({
  rows,
  labelKey = "key",
  badge = false,
}: {
  rows: RecoverySummary["by_loss_category"];
  labelKey?: "key" | "restaurant_name";
  badge?: boolean;
}) {
  if (rows.length === 0) {
    return <EmptyState title="Aucune donnee" />;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Cle</th>
            <th>Total</th>
            <th>Detecte</th>
            <th>Contestable</th>
            <th>Recupere</th>
            <th>Refuse</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{badge ? <StatusBadge status={row.key} /> : row[labelKey] ?? row.key}</td>
              <td>{row.count}</td>
              <td>{formatCurrency(row.detected_amount)}</td>
              <td>{formatCurrency(row.claimable_amount)}</td>
              <td>{formatCurrency(row.recovered_amount)}</td>
              <td>{formatCurrency(row.refused_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function toRecoveryFilters(filters: FilterState): RecoveryFilters {
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
