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

  const nextActionCount = nextActions ? countNextActions(nextActions) : 0;
  const canSeeBusinessMetrics = user?.role === "owner" || user?.role === "manager";

  return (
    <section className="page-section page-section--simple">
      <div className="simple-hero">
        <div className="heading-copy">
          <p className="eyebrow">TENNET</p>
          <h1>{user?.role === "staff" ? "Mes preuves a faire" : "A faire maintenant"}</h1>
          <p>
            TENNET met devant toi les prochaines actions utiles. Les tableaux et details restent disponibles, mais ils
            ne doivent plus te ralentir.
          </p>
        </div>
        <div className="simple-hero__actions">
          {canSeeBusinessMetrics ? (
            <Link href="/smart-import" className="button">
              Deposer des fichiers
            </Link>
          ) : null}
          <Link href="/evidence-tasks" className="secondary-button">
            Preuves
          </Link>
          {canSeeBusinessMetrics ? (
            <Link href="/recovery" className="secondary-button">
              Recuperation
            </Link>
          ) : null}
        </div>
      </div>

      <ApiError error={error} />

      {summary ? (
        <>
          {nextActions ? (
            <section className="tool-panel tool-panel--primary">
              <div className="section-heading">
                <div>
                  <h2>{nextActionCount === 0 ? "Rien d'urgent" : `${nextActionCount} action(s) a traiter`}</h2>
                  <p className="muted">
                    {user?.role === "staff"
                      ? "Tu vois uniquement les preuves et uploads autorises pour le terrain."
                      : "TENNET priorise les preuves, imports, refus, relances et dossiers a fort montant."}
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

          <div className="simple-metrics">
            <StatCard label="Actions" value={nextActionCount} detail="A traiter en priorite" />
            <StatCard label="Dossiers visibles" value={summary.total_orders} detail="Pour ton role" />
            {canSeeBusinessMetrics ? (
              <>
                <StatCard label="En attente" value={formatCurrency(summary.total_pending_amount)} detail="Encore a suivre" />
                <StatCard label="Recupere" value={formatCurrency(summary.total_recovered_amount)} detail="Paiements confirmes" />
                <StatCard label="Refuse" value={formatCurrency(summary.total_refused_amount)} detail="A relancer ou appeler" />
              </>
            ) : null}
          </div>

          {canSeeBusinessMetrics ? (
            <details className="simple-details">
              <summary>Voir les chiffres et tableaux detailles</summary>
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
            </details>
          ) : null}
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

function countNextActions(nextActions: WorkspaceNextActionsResponse): number {
  return (
    nextActions.urgent.length +
    nextActions.today.length +
    nextActions.blocked.length +
    nextActions.high_value.length +
    nextActions.this_week.length
  );
}

function formatPercent(value: string | number | null): string {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(numericValue * 100)} %`;
}
