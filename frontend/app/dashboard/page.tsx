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
  type DashboardSummary,
  type SmartImportFileDecision,
  type WorkspaceNextActionsResponse,
  type WorkspaceMachineRunResponse,
  formatCurrency,
} from "@/lib/api";

const acceptedTypes = ".csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.zip,image/*,application/pdf";

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [nextActions, setNextActions] = useState<WorkspaceNextActionsResponse | null>(null);
  const [machineResult, setMachineResult] = useState<WorkspaceMachineRunResponse | null>(null);
  const [homeFiles, setHomeFiles] = useState<File[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [pilotError, setPilotError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [pilotRunning, setPilotRunning] = useState(false);
  const [importRunning, setImportRunning] = useState(false);

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
    setMachineResult(null);

    try {
      const result = await api.runWorkspaceMachine({ trigger: "manual", sync_gmail: true, run_autopilot: true });
      setMachineResult(result);
      setNextActions(result.next_actions);
      await loadDashboard();
    } catch (apiError) {
      setPilotError(apiError);
    } finally {
      setPilotRunning(false);
    }
  }

  async function runSmartImportFromDashboard() {
    if (homeFiles.length === 0) {
      setPilotError(new Error("Ajoute au moins un fichier."));
      return;
    }
    setImportRunning(true);
    setPilotError(null);
    setMachineResult(null);
    try {
      const preview = await api.previewSmartImport(homeFiles);
      const decisions: SmartImportFileDecision[] = preview.files.map((file) => ({
        file_id: file.id,
        action: file.recommended_action,
        report_type: file.detected_report_type ?? "combined_report",
        restaurant_id: null,
      }));
      await api.confirmSmartImport(preview.batch_preview_id, decisions);
      const result = await api.runWorkspaceMachine({
        trigger: "smart_import",
        smart_import_batch_id: preview.batch_preview_id,
        sync_gmail: true,
        run_autopilot: true,
      });
      setMachineResult(result);
      setNextActions(result.next_actions);
      setHomeFiles([]);
      await loadDashboard();
    } catch (apiError) {
      setPilotError(apiError);
    } finally {
      setImportRunning(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du dashboard" />;
  }

  const nextActionCount = nextActions ? countNextActions(nextActions) : 0;
  const canSeeBusinessMetrics = user?.role === "owner" || user?.role === "manager";

  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero">
        <div className="heading-copy">
          <p className="eyebrow">TENNET</p>
          <h1>{user?.role === "staff" ? "Mes preuves a faire" : "Machine de recuperation"}</h1>
          <p>
            Depose tes exports Uber, preuves ou ZIP. TENNET classe, traite, detecte, prepare les dossiers et lance les
            actions autorisees par tes regles.
          </p>
        </div>
        {canSeeBusinessMetrics ? (
          <div className={`machine-command ${pilotRunning || importRunning ? "machine-command--running" : ""}`}>
            <div className="machine-ring" aria-hidden="true">
              <span />
            </div>
            <div className="machine-command__content">
              <strong>{pilotRunning || importRunning ? "TENNET travaille" : "Lancer TENNET"}</strong>
              <span>{homeFiles.length > 0 ? `${homeFiles.length} fichier(s) prets` : "Import massif ou passage complet"}</span>
            </div>
          </div>
        ) : null}
        <div className="simple-hero__actions machine-hero__actions">
          {canSeeBusinessMetrics ? (
            <label className="secondary-button machine-file-button" htmlFor="dashboard-smart-files">
              Deposer fichiers
            </label>
          ) : null}
          {canSeeBusinessMetrics ? (
            <input
              id="dashboard-smart-files"
              className="machine-file-input"
              type="file"
              multiple
              accept={acceptedTypes}
              onChange={(event) => setHomeFiles(Array.from(event.target.files ?? []))}
            />
          ) : null}
          {canSeeBusinessMetrics && homeFiles.length > 0 ? (
            <button
              type="button"
              className="button button--hero"
              disabled={pilotRunning || importRunning}
              onClick={() => void runSmartImportFromDashboard()}
            >
              {importRunning ? "Traitement" : "Importer et lancer"}
            </button>
          ) : null}
          {canSeeBusinessMetrics ? (
            <button type="button" className="button button--hero" disabled={pilotRunning || importRunning} onClick={() => void runTennetPilot()}>
              {pilotRunning ? "TENNET travaille" : "Passage complet"}
            </button>
          ) : null}
        </div>
      </div>

      {canSeeBusinessMetrics ? (
        <section className="home-flow-panel" aria-label="Parcours principaux TENNET">
          <Link href="/remboursements" className="home-flow-card home-flow-card--refunds">
            <span>Remboursements</span>
            <strong>Demandes client, articles manquants, qualite, ajustements</strong>
            <small>Preuves, mails Uber, relances et paiements rattaches au bon restaurant.</small>
          </Link>
          <Link href="/annulations" className="home-flow-card home-flow-card--cancellations">
            <span>Annulations</span>
            <strong>Commandes annulees, non compensees ou partiellement payees</strong>
            <small>Tickets, preparation, gaspillage, reconciliation et contestation.</small>
          </Link>
          <Link href="/evidence-tasks" className="home-flow-card home-flow-card--proofs">
            <span>Preuves</span>
            <strong>Ce qu'il faut photographier ou importer maintenant</strong>
            <small>Chaque preuve indique si elle concerne un remboursement ou une annulation.</small>
          </Link>
          <Link href="/smart-import" className="home-flow-card home-flow-card--imports">
            <span>Imports</span>
            <strong>Voir ce que TENNET a classe et traite</strong>
            <small>Fichiers traites, sources officielles gardees, doublons controles et suite logique.</small>
          </Link>
        </section>
      ) : null}

      <ApiError error={error} />
      <ApiError error={pilotError} />
      {machineResult ? <MachineResultBox result={machineResult} /> : null}

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

function MachineResultBox({ result }: { result: WorkspaceMachineRunResponse }) {
  return (
    <section className={`machine-result machine-result--${result.status}`}>
      <div>
        <strong>TENNET a termine son passage</strong>
        <p>Destinataire Uber configure : {result.recipient_email}. Les conditions non remplies restent visibles.</p>
      </div>
      <div className="simple-pilot-grid">
        <div className="detail-item">
          <span>Etapes</span>
          <strong>{result.stages.length}</strong>
        </div>
        <div className="detail-item">
          <span>Cree</span>
          <strong>{sumStages(result, "created_count")}</strong>
        </div>
        <div className="detail-item">
          <span>Envoyes</span>
          <strong>{sumStages(result, "sent_count")}</strong>
        </div>
        <div className="detail-item">
          <span>A exploiter</span>
          <strong>{sumStages(result, "skipped_count") + sumStages(result, "failed_count")}</strong>
        </div>
      </div>
      <div className="machine-stage-list">
        {result.stages.map((stage) => (
          <article key={stage.name} className={`machine-stage machine-stage--${stage.status}`}>
            <strong>{stageLabel(stage.name)}</strong>
            <span>{stageStatusLabel(stage.status)}</span>
            <small>
              {stage.processed_count} traite(s), {stage.created_count} cree(s), {stage.sent_count} envoye(s)
            </small>
          </article>
        ))}
      </div>
      {machineWarnings(result).length > 0 ? (
        <div className="chip-list">
          {machineWarnings(result).map((warning) => (
            <span key={warning} className="chip">
              {warning}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function sumStages(result: WorkspaceMachineRunResponse, key: "created_count" | "sent_count" | "skipped_count" | "failed_count") {
  return result.stages.reduce((total, stage) => total + stage[key], 0);
}

function machineWarnings(result: WorkspaceMachineRunResponse): string[] {
  return result.stages.flatMap((stage) => [...stage.warnings, ...stage.errors]);
}

function stageLabel(name: string): string {
  const labels: Record<string, string> = {
    deductions: "Deductions",
    claim_orders: "Dossiers",
    drafts: "Brouillons",
    followups: "Relances",
    appeals: "Appels",
    gmail_sync: "Gmail",
    autopilot: "AutoPilot",
  };
  return labels[name] ?? name;
}

function stageStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: "termine",
    skipped: "non requis",
    warning: "a verifier",
    failed: "erreur",
  };
  return labels[status] ?? status;
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
