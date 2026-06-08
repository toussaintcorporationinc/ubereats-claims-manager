"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type DashboardSummary, formatCurrency } from "@/lib/api";

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getDashboardSummary()
      .then(setSummary)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement du dashboard" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Dashboard</p>
          <h1>Vue operationnelle</h1>
        </div>
        <div className="actions">
          <Link href="/orders/new" className="button">
            Nouvelle commande
          </Link>
          {user?.role === "owner" ? (
            <Link href="/restaurants/new" className="secondary-button">
              Nouveau restaurant
            </Link>
          ) : null}
        </div>
      </div>

      <ApiError error={error} />

      {summary ? (
        <>
          <div className="stats-grid">
            <StatCard label="Dossiers" value={summary.total_orders} />
            <StatCard label="Total reclame" value={formatCurrency(summary.total_claimed_amount)} />
            <StatCard label="Recupere" value={formatCurrency(summary.total_recovered_amount)} />
            <StatCard label="En attente" value={formatCurrency(summary.total_pending_amount)} />
            <StatCard label="Refuse" value={formatCurrency(summary.total_refused_amount)} />
            <StatCard label="Acceptes" value={summary.accepted_count} />
            <StatCard label="Paiement a verifier" value={summary.payment_to_verify_count} />
            <StatCard label="Paiements confirmes" value={summary.payment_confirmed_count} />
            <StatCard label="Refus clients" value={summary.refused_count} />
            <StatCard label="Revue manuelle" value={summary.manual_review_count} />
            <StatCard label="Attente reponse" value={summary.pending_response_count} />
            <StatCard label="Relances dues" value={summary.followups_due_count} />
            <StatCard label="Relances en attente" value={summary.followups_pending_count} />
            <StatCard label="Escalades dues" value={summary.escalations_due_count} />
            <StatCard label="Revues a faire" value={summary.manual_review_due_count} />
          </div>

          <div className="grid-two">
            <section className="tool-panel">
              <h2>Dossiers par statut</h2>
              {Object.keys(summary.orders_by_status).length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Statut</th>
                        <th>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(summary.orders_by_status).map(([status, total]) => (
                        <tr key={status}>
                          <td>
                            <StatusBadge status={status} />
                          </td>
                          <td>{total}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Aucun dossier" />
              )}
            </section>

            <section className="tool-panel">
              <h2>Dossiers par restaurant</h2>
              {summary.orders_by_restaurant.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Restaurant</th>
                        <th>Dossiers</th>
                        <th>Total reclame</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.orders_by_restaurant.map((restaurant) => (
                        <tr key={restaurant.restaurant_id}>
                          <td>{restaurant.restaurant_name}</td>
                          <td>{restaurant.total_orders}</td>
                          <td>{formatCurrency(restaurant.total_claimed_amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Aucun restaurant" />
              )}
            </section>
          </div>
        </>
      ) : null}
    </section>
  );
}
