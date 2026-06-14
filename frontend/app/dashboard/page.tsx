"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import PremiumEmptyState from "@/components/PremiumEmptyState";
import RecoveryActionCard from "@/components/RecoveryActionCard";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  type AutopilotRunDetail,
  type DashboardSummary,
  type GmailInboundSyncResponse,
  type WorkspaceNextActionsResponse,
  formatCurrency,
} from "@/lib/api";

type PilotRunResult = {
  sync: GmailInboundSyncResponse | null;
  autopilot: AutopilotRunDetail | null;
  warnings: string[];
};

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [nextActions, setNextActions] = useState<WorkspaceNextActionsResponse | null>(null);
  const [pilotResult, setPilotResult] = useState<PilotRunResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pilotError, setPilotError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [pilotRunning, setPilotRunning] = useState(false);

  const loadDashboard = useCallback(async () => {
    const [summaryData, actionsData] = await Promise.all([api.getDashboardSummary(), api.getWorkspaceNextActions()]);
    setSummary(summaryData);
    setNextActions(actionsData);
  }, []);

  useEffect(() => {
    loadDashboard()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadDashboard]);

  async function runTennetPilot() {
    setPilotRunning(true);
    setPilotError(null);
    setPilotResult(null);

    const warnings: string[] = [];
    let sync: GmailInboundSyncResponse | null = null;
    let autopilot: AutopilotRunDetail | null = null;

    try {
      try {
        sync = await api.syncInboundGmail({
          lookback_days: 30,
          max_messages: 100,
          analyze_responses: true,
          apply_reviews: true,
          run_autopilot_after_sync: true,
        });
      } catch (syncError) {
        warnings.push(`Gmail bloque: ${errorMessage(syncError)}`);
      }

      try {
        autopilot = await api.runAutopilot({ mode: "all", restaurant_id: null });
      } catch (autopilotError) {
        warnings.push(`AutoPilot bloque: ${errorMessage(autopilotError)}`);
      }

      if (!sync && !autopilot) {
        setPilotError(new Error(warnings.join(" | ") || "TENNET n'a rien pu lancer."));
      }

      setPilotResult({ sync, autopilot, warnings });
      await loadDashboard();
    } finally {
      setPilotRunning(false);
    }
  }

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
            <button type="button" className="button button--hero" disabled={pilotRunning} onClick={() => void runTennetPilot()}>
              {pilotRunning ? "TENNET travaille" : "Faire bosser TENNET"}
            </button>
          ) : null}
          {canSeeBusinessMetrics ? (
            <Link href="/smart-import" className="secondary-button">
              Deposer fichiers
            </Link>
          ) : null}
          <Link href="/evidence-tasks" className="secondary-button">
            Preuves
          </Link>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={pilotError} />
      {pilotResult ? <PilotResultBox result={pilotResult} /> : null}

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

function PilotResultBox({ result }: { result: PilotRunResult }) {
  const sync = result.sync;
  const autopilot = result.autopilot?.run ?? null;

  return (
    <section className="simple-callout simple-callout--pilot">
      <div>
        <strong>TENNET a termine son passage automatique</strong>
        <p>Il a traite ce qui etait faisable, et bloque ce qui demande une condition manquante.</p>
      </div>
      <div className="simple-pilot-grid">
        <div className="detail-item">
          <span>Emails analyses</span>
          <strong>{sync ? sync.analyzed_messages : 0}</strong>
        </div>
        <div className="detail-item">
          <span>Decisions appliquees</span>
          <strong>{sync ? sync.applied_reviews : 0}</strong>
        </div>
        <div className="detail-item">
          <span>Envoyes</span>
          <strong>{(sync?.autopilot_sent_count ?? 0) + (autopilot?.sent_count ?? 0)}</strong>
        </div>
        <div className="detail-item">
          <span>Bloques</span>
          <strong>{(sync?.autopilot_skipped_count ?? 0) + (autopilot?.skipped_count ?? 0)}</strong>
        </div>
      </div>
      {result.warnings.length > 0 ? (
        <div className="chip-list">
          {result.warnings.map((warning) => (
            <span key={warning} className="chip">
              {warning}
            </span>
          ))}
        </div>
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

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "condition non remplie";
}
