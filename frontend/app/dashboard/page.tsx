"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import PremiumEmptyState from "@/components/PremiumEmptyState";
import RecoveryActionCard from "@/components/RecoveryActionCard";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type DashboardSummary, type WorkspaceNextActionsResponse, formatCurrency } from "@/lib/api";

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [nextActions, setNextActions] = useState<WorkspaceNextActionsResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getDashboardSummary(), api.getWorkspaceNextActions()])
      .then(([summaryData, actionsData]) => {
        setSummary(summaryData);
        setNextActions(actionsData);
      })
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
          {nextActions ? (
            <section className="tool-panel">
              <div className="section-heading">
                <div>
                  <h2>{user?.role === "staff" ? "Mes preuves a fournir" : "A faire maintenant"}</h2>
                  <p className="muted">
                    {user?.role === "staff"
                      ? "Les actions terrain sont limitees aux preuves et aux uploads autorises."
                      : "TENNET priorise les actions pour qu'aucune perte detectee ne reste sans revue."}
                  </p>
                </div>
                {user?.role !== "staff" ? (
                  <Link href="/recovery/actions" className="secondary-button">
                    File actions
                  </Link>
                ) : (
                  <Link href="/evidence-tasks" className="secondary-button">
                    Preuves
                  </Link>
                )}
              </div>
              <NextActionsGrid nextActions={nextActions} />
            </section>
          ) : null}

          <div className="stats-grid">
            <StatCard label="Dossiers" value={summary.total_orders} />
            <StatCard label="Total reclame" value={formatCurrency(summary.total_claimed_amount)} />
            <StatCard label="Recupere" value={formatCurrency(summary.total_recovered_amount)} />
            <StatCard label="En attente" value={formatCurrency(summary.total_pending_amount)} />
            <StatCard label="Refuse" value={formatCurrency(summary.total_refused_amount)} />
            <StatCard label="Taux de reussite" value={formatPercent(summary.success_rate)} />
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

          <div className="grid-two">
            <section className="tool-panel">
              <h2>Top restaurants par montant reclame</h2>
              {summary.top_restaurants_by_claimed_amount.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Restaurant</th>
                        <th>Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.top_restaurants_by_claimed_amount.map((restaurant) => (
                        <tr key={restaurant.restaurant_id}>
                          <td>{restaurant.restaurant_name}</td>
                          <td>{formatCurrency(restaurant.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Aucun montant" />
              )}
            </section>

            <section className="tool-panel">
              <h2>Top restaurants par montant en attente</h2>
              {summary.top_restaurants_by_pending_amount.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Restaurant</th>
                        <th>Montant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {summary.top_restaurants_by_pending_amount.map((restaurant) => (
                        <tr key={restaurant.restaurant_id}>
                          <td>{restaurant.restaurant_name}</td>
                          <td>{formatCurrency(restaurant.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="Aucun montant en attente" />
              )}
            </section>
          </div>
        </>
      ) : null}
    </section>
  );
}

function NextActionsGrid({ nextActions }: { nextActions: WorkspaceNextActionsResponse }) {
  const actions = [
    ...nextActions.urgent,
    ...nextActions.today,
    ...nextActions.blocked,
    ...nextActions.high_value,
    ...nextActions.this_week,
  ].slice(0, 6);

  if (actions.length === 0) {
    return <PremiumEmptyState title="Rien d'urgent" description="Les dossiers visibles sont a jour pour votre role." />;
  }

  return (
    <div className="premium-card-grid">
      {actions.map((action) => (
        <RecoveryActionCard key={`${action.action_type}-${action.action_url}`} action={action} />
      ))}
    </div>
  );
}

function formatPercent(value: string | number | null): string {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(numericValue * 100)} %`;
}
