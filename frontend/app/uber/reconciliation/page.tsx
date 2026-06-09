"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { api, formatCurrency, formatDate, type Restaurant, type UberReconciliationRun, type UberReconciliationRunResponse } from "@/lib/api";

export default function UberReconciliationPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [runs, setRuns] = useState<UberReconciliationRun[]>([]);
  const [latestRun, setLatestRun] = useState<UberReconciliationRunResponse | null>(null);
  const [restaurantId, setRestaurantId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  async function loadData() {
    const [restaurantData, runData] = await Promise.all([api.getRestaurants(), api.getUberReconciliationRuns()]);
    setRestaurants(restaurantData);
    setRuns(runData);
  }

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const result = await api.runUberReconciliation({
        restaurant_id: restaurantId ? Number(restaurantId) : null,
        date_from: dateFrom || null,
        date_to: dateTo || null,
      });
      setLatestRun(result);
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement reconciliation Uber" />;
  }

  const displayedRun = latestRun ?? runs[0] ?? null;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Reconciliation 6 mois</h1>
          <p>Aucune contestation n&apos;est envoyee automatiquement.</p>
        </div>
        <Link className="secondary-button" href="/uber/reconciliation/runs">
          Historique analyses
        </Link>
      </div>

      <ApiError error={error} />

      <form className="tool-panel" onSubmit={handleRun}>
        <div className="section-heading">
          <h2>Lancer une analyse</h2>
          <StatusBadge status="manual_review" />
        </div>
        <div className="form-grid">
          <label>
            Restaurant
            <select value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)}>
              <option value="">Tous les restaurants accessibles</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Date debut
            <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </label>
          <label>
            Date fin
            <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </label>
        </div>
        <button type="submit" className="button" disabled={working}>
          Lancer analyse 6 mois
        </button>
      </form>

      {displayedRun ? (
        <>
          <div className="stats-grid">
            <StatCard label="Commandes analysees" value={displayedRun.total_orders_analyzed} />
            <StatCard label="Annulees" value={displayedRun.canceled_orders_count} />
            <StatCard label="Non compensees" value={displayedRun.not_compensated_count} />
            <StatCard label="Partielles" value={displayedRun.partially_compensated_count} />
            <StatCard label="Deja reclamees" value={displayedRun.already_claimed_count} />
            <StatCard label="Besoin preuve" value={displayedRun.needs_evidence_count} />
            <StatCard label="Revue manuelle" value={displayedRun.manual_review_count} />
            <StatCard label="Montant recuperable estime" value={formatCurrency(displayedRun.total_missing_amount)} />
          </div>
          {"run_id" in displayedRun ? (
            <Link className="button" href={`/uber/reconciliation/runs/${displayedRun.run_id}`}>
              Voir les resultats
            </Link>
          ) : (
            <Link className="button" href={`/uber/reconciliation/runs/${displayedRun.id}`}>
              Voir les resultats
            </Link>
          )}
        </>
      ) : (
        <EmptyState title="Aucune analyse de reconciliation" />
      )}

      {runs.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Periode</th>
                <th>Statut</th>
                <th>Manquant</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.slice(0, 5).map((run) => (
                <tr key={run.id}>
                  <td>{formatDate(run.created_at)}</td>
                  <td>
                    {formatDate(run.date_from)} - {formatDate(run.date_to)}
                  </td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td>{formatCurrency(run.total_missing_amount)}</td>
                  <td>
                    <Link className="secondary-button" href={`/uber/reconciliation/runs/${run.id}`}>
                      Detail
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
