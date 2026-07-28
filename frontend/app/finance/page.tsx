"use client";

import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import {
  api,
  formatCurrency,
  type DashboardSummary,
  type GmailWarRoomDashboard,
} from "@/lib/api";

const POLL_INTERVAL_MS = 15000;

export default function FinancePage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [warRoom, setWarRoom] = useState<GmailWarRoomDashboard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadFinance = useCallback(async () => {
    try {
      const [dashboardSummary, gmailWarRoom] = await Promise.all([
        api.getDashboardSummary(),
        api.getGmailWarRoom(80, false),
      ]);
      setSummary(dashboardSummary);
      setWarRoom(gmailWarRoom);
      setError(null);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFinance();
    const interval = window.setInterval(() => {
      void loadFinance();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [loadFinance]);

  if (loading) {
    return <LoadingState label="Chargement Finance" />;
  }

  const restaurants = summary?.orders_by_restaurant ?? [];
  const topPending = summary?.top_restaurants_by_pending_amount ?? [];

  return (
    <section className="page-section page-section--simple">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Finance</p>
          <h1>Argent suivi par TENNET</h1>
          <p>
            Une vue simple pour verifier les paiements accordes ou confirmes par Uber, les montants encore a suivre,
            les refus a relancer et les signaux positifs detectes dans Gmail.
          </p>
        </div>
      </div>

      {error ? <ApiError error={error} /> : null}

      <div className="stats-grid">
        <StatCard label="Recu" value={formatCurrency(summary?.total_recovered_amount ?? 0)} detail="paiements confirmes par Uber" />
        <StatCard
          label="Accorde, a verifier"
          value={formatCurrency(summary?.total_approved_amount ?? 0)}
          detail="accord Gmail, versement a controler"
        />
        <StatCard label="A suivre" value={formatCurrency(summary?.total_pending_amount ?? 0)} detail="encore ouvert" />
        <StatCard label="Refuse" value={formatCurrency(summary?.total_refused_amount ?? 0)} detail="a relancer si etoile active" />
        <StatCard label="Signaux positifs 24h" value={warRoom?.summary.positive_responses_last_24h ?? 0} detail="Gmail" />
        <StatCard label="Threads surveilles" value={warRoom?.summary.active_watched_threads ?? 0} detail="etoiles actives" />
        <StatCard label="Backlog Gmail" value={warRoom?.summary.backlog_remaining ?? 0} detail="reste a traiter" />
      </div>

      <div className="grid-two">
        <section className="tool-panel">
          <h2>Restaurants</h2>
          {restaurants.length > 0 ? (
            <div className="responsive-table">
              <table>
                <thead>
                  <tr>
                    <th>Restaurant</th>
                    <th>Dossiers</th>
                    <th>Reclame</th>
                    <th>Recu</th>
                  </tr>
                </thead>
                <tbody>
                  {restaurants.map((restaurant) => (
                    <tr key={restaurant.restaurant_id}>
                      <td>{restaurant.restaurant_name}</td>
                      <td>{restaurant.total_orders}</td>
                      <td>{formatCurrency(restaurant.total_claimed_amount)}</td>
                      <td>{formatCurrency(restaurant.total_recovered_amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Aucune ligne finance" description="Les paiements positifs Gmail apparaitront ici quand ils seront rattaches." />
          )}
        </section>

        <section className="tool-panel">
          <h2>A suivre en priorite</h2>
          {topPending.length > 0 ? (
            <div className="relance-card-list">
              {topPending.map((restaurant) => (
                <article key={restaurant.restaurant_id} className="relance-card">
                  <div className="relance-card__top">
                    <strong>{restaurant.restaurant_name}</strong>
                    <span>{formatCurrency(restaurant.amount)}</span>
                  </div>
                  <p>Montant encore ouvert. TENNET continue la surveillance Gmail si le fil est etoile.</p>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState title="Rien a prioriser" description="Aucun montant ouvert majeur pour le moment." />
          )}
        </section>
      </div>
    </section>
  );
}
