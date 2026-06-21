"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import PremiumEmptyState from "@/components/PremiumEmptyState";
import RecoveryActionCard from "@/components/RecoveryActionCard";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { buildMachineSmartImportDecisions } from "@/lib/smartImportMachine";
import {
  api,
  type DashboardSummary,
  type GmailInboundStatus,
  type RecoveryMachineRail,
  type RecoveryMachineRailKey,
  type RecoveryMachineResponse,
  type RecoveryMachineStage,
  type WorkspaceNextActionsResponse,
  type WorkspaceMachineRunResponse,
  type WorkspaceUnclassifiedResponse,
  formatCurrency,
  formatDateTime,
} from "@/lib/api";

const acceptedTypes = ".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.zip,image/*,application/pdf";

export default function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [nextActions, setNextActions] = useState<WorkspaceNextActionsResponse | null>(null);
  const [unclassified, setUnclassified] = useState<WorkspaceUnclassifiedResponse | null>(null);
  const [recoveryMachine, setRecoveryMachine] = useState<RecoveryMachineResponse | null>(null);
  const [gmailWorker, setGmailWorker] = useState<GmailInboundStatus | null>(null);
  const [gmailWorkerError, setGmailWorkerError] = useState<unknown>(null);
  const [machineResult, setMachineResult] = useState<WorkspaceMachineRunResponse | null>(null);
  const [railFiles, setRailFiles] = useState<Record<RecoveryMachineRailKey, File[]>>({
    refunds: [],
    cancellations: [],
  });
  const [error, setError] = useState<unknown>(null);
  const [pilotError, setPilotError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [pilotRunning, setPilotRunning] = useState(false);
  const [railRunning, setRailRunning] = useState<RecoveryMachineRailKey | null>(null);
  const autoPassageStarted = useRef(false);
  const canRunRecoveryMachine = user?.role === "owner" || user?.role === "manager";

  const loadDashboard = useCallback(async () => {
    setGmailWorkerError(null);
    const [summaryData, actionsData, recoveryMachineData, unclassifiedData, gmailWorkerResult] = await Promise.all([
      api.getDashboardSummary(),
      api.getWorkspaceNextActions(),
      api.getWorkspaceRecoveryMachine(),
      api.getWorkspaceUnclassified(),
      canRunRecoveryMachine
        ? api
            .getInboundStatus()
            .then((data) => ({ data, error: null }))
            .catch((apiError) => ({ data: null, error: apiError }))
        : Promise.resolve({ data: null, error: null }),
    ]);
    setSummary(summaryData);
    setNextActions(actionsData);
    setRecoveryMachine(recoveryMachineData);
    setUnclassified(unclassifiedData);
    setGmailWorker(gmailWorkerResult.data);
    setGmailWorkerError(gmailWorkerResult.error);
  }, [canRunRecoveryMachine]);

  useEffect(() => {
    loadDashboard()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadDashboard]);

  useEffect(() => {
    if (loading || !canRunRecoveryMachine || autoPassageStarted.current) {
      return;
    }
    const storageKey = "tennet:auto-passage-complet:last-run";
    const now = Date.now();
    const lastRun = Number(window.sessionStorage.getItem(storageKey) ?? 0);
    if (Number.isFinite(lastRun) && now - lastRun < 15 * 60 * 1000) {
      return;
    }
    autoPassageStarted.current = true;
    window.sessionStorage.setItem(storageKey, String(now));
    void runTennetPilot();
  }, [canRunRecoveryMachine, loading]);

  async function runTennetPilot() {
    setPilotRunning(true);
    setPilotError(null);
    setMachineResult(null);

    try {
      const result = await api.runWorkspaceMachine({
        trigger: "manual",
        sync_gmail: true,
        run_autopilot: true,
        run_historical_cleanup: true,
      });
      setMachineResult(result);
      setNextActions(result.next_actions);
      await loadDashboard();
    } catch (apiError) {
      setPilotError(apiError);
    } finally {
      setPilotRunning(false);
    }
  }

  async function runRecoveryRailImport(trigger: RecoveryMachineRailKey, selectedFiles?: File[]) {
    const files = selectedFiles ?? railFiles[trigger];
    if (files.length === 0) {
      setPilotError(
        new Error(
          trigger === "refunds"
            ? "Depose les preuves de remboursement avant de lancer TENNET."
            : "Depose les preuves d'annulation avant de lancer TENNET.",
        ),
      );
      return;
    }

    setRailRunning(trigger);
    setPilotError(null);
    setMachineResult(null);
    try {
      const preview = await api.previewSmartImport(files);
      const decisions = buildMachineSmartImportDecisions(preview.files, trigger);
      await api.confirmSmartImport(preview.batch_preview_id, decisions);
      const result = await api.runWorkspaceMachine({
        trigger,
        smart_import_batch_id: preview.batch_preview_id,
        sync_gmail: true,
        run_autopilot: true,
        run_historical_cleanup: true,
      });
      setMachineResult(result);
      setNextActions(result.next_actions);
      setRailFiles((current) => ({ ...current, [trigger]: [] }));
      await loadDashboard();
    } catch (apiError) {
      setPilotError(apiError);
    } finally {
      setRailRunning(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du dashboard" />;
  }

  const nextActionCount = nextActions ? countNextActions(nextActions) : 0;
  const canSeeBusinessMetrics = canRunRecoveryMachine;

  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero machine-hero--focus machine-hero--home">
        <div className="machine-hero__main machine-hero__main--simple">
          <div className="heading-copy">
            <p className="eyebrow">TENNET</p>
            <h1>{user?.role === "staff" ? "Mes preuves a faire" : "Machine de recuperation"}</h1>
            <p>
              Deux parcours clairs : remboursements et annulations. Tu deposes les photos de tickets agrafes,
              TENNET lit, rattache, prepare les demandes, suit Gmail et remonte les blocages reels avec une raison claire.
            </p>
          </div>
          {canSeeBusinessMetrics ? (
            <div
              className={`machine-command ${pilotRunning || railRunning ? "machine-command--running" : ""}`}
            >
              <div className="machine-ring" aria-hidden="true">
                <span />
              </div>
              <div className="machine-command__content">
                <strong>{pilotRunning || railRunning ? "TENNET travaille" : "Machine active"}</strong>
                <span>
                  {railRunning === "refunds"
                    ? "Remboursements en cours"
                    : railRunning === "cancellations"
                      ? "Annulations en cours"
                    : recoveryMachine
                      ? `${recoveryMachine.global_progress_percent}% du parcours`
                      : "Surveillance continue"}
                </span>
              </div>
            </div>
          ) : null}
          <div className="home-machine-status">
            <strong>Passage complet automatique</strong>
            <p>
              La synchronisation, les rapprochements et les relances autorisees tournent en arriere-plan. Un depot de
              preuves lance directement le traitement du parcours choisi.
            </p>
            {!canSeeBusinessMetrics ? (
              <Link href="/evidence-tasks" className="button button--hero">
                Voir mes preuves
              </Link>
            ) : null}
          </div>
        </div>
        {canSeeBusinessMetrics && recoveryMachine ? (
          <RecoveryMachineFocusPanel
            machine={recoveryMachine}
            filesByRail={railFiles}
            runningRail={railRunning}
            busy={pilotRunning}
            onFilesChange={(railKey, files) => {
              setRailFiles((current) => ({ ...current, [railKey]: files }));
              if (files.length > 0) {
                void runRecoveryRailImport(railKey, files);
              }
            }}
          />
        ) : null}
      </div>

      {canSeeBusinessMetrics && gmailWorker ? <GmailWorkerPanel status={gmailWorker} /> : null}
      {canSeeBusinessMetrics && !gmailWorker && gmailWorkerError ? (
        <GmailWorkerUnavailablePanel error={gmailWorkerError} />
      ) : null}

      <ApiError error={error} />
      <ApiError error={pilotError} />
      {machineResult ? <MachineResultBox result={machineResult} /> : null}
      {unclassified && unclassified.total_count > 0 ? <UnclassifiedPanel unclassified={unclassified} /> : null}

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

function GmailWorkerPanel({ status }: { status: GmailInboundStatus }) {
  const cycle = status.last_cycle;
  const blockers = status.last_autopilot_blockers ?? [];
  const stateLabel =
    status.worker_state === "active"
      ? "Surveillance active"
      : status.worker_state === "attention"
        ? "Attention requise"
        : "Desactive";
  const nextSyncLabel =
    status.seconds_until_next_sync !== null && status.seconds_until_next_sync !== undefined
      ? `dans ${formatDuration(status.seconds_until_next_sync)}`
      : formatDateTime(status.next_sync_at);
  const cycleMessage = cycle
    ? `${cycle.accounts_synced}/${cycle.accounts_checked} compte(s), ${cycle.synced_messages} mail(s) lu(s), ${cycle.negative_responses_detected} refus detecte(s), ${cycle.autopilot_sent_count} relance(s) envoyee(s).`
    : "Aucun passage automatique enregistre encore.";

  return (
    <section className={`gmail-worker-card gmail-worker-card--${status.worker_state}`}>
      <div className="gmail-worker-card__header">
        <div>
          <p className="eyebrow">Gmail / IA 24-7</p>
          <h2>{stateLabel}</h2>
          <p>{status.worker_message ?? "TENNET surveille les reponses Uber en arriere-plan."}</p>
        </div>
        <StatusBadge
          status={
            status.worker_state === "active"
              ? "active"
              : status.worker_state === "attention"
                ? "manual_review"
                : "disabled"
          }
        />
      </div>

      <div className="gmail-worker-grid">
        <div>
          <span>Comptes Gmail</span>
          <strong>{status.connected_accounts_count}</strong>
          <small>
            {status.connected_account_emails.length > 0
              ? status.connected_account_emails.join(", ")
              : "Aucun compte connecte"}
          </small>
        </div>
        <div>
          <span>Dernier passage</span>
          <strong>{formatDateTime(cycle?.created_at ?? status.last_success_at ?? status.last_sync_at)}</strong>
          <small>{cycleMessage}</small>
        </div>
        <div>
          <span>Prochain passage</span>
          <strong>{status.auto_sync_enabled ? nextSyncLabel : "sync automatique off"}</strong>
          <small>Intervalle: {status.auto_sync_interval_seconds ? formatDuration(status.auto_sync_interval_seconds) : "-"}</small>
        </div>
        <div>
          <span>Relances</span>
          <strong>{cycle ? cycle.autopilot_sent_count : 0} envoyee(s)</strong>
          <small>
            {cycle
              ? `${cycle.autopilot_skipped_count} bloquee(s), ${cycle.autopilot_failed_count} erreur(s)`
              : "En attente du prochain cycle"}
          </small>
        </div>
      </div>

      {blockers.length > 0 ? (
        <div className="gmail-worker-blockers">
          <strong>Pourquoi TENNET n'a pas relance</strong>
          <div>
            {blockers.map((blocker) => (
              <span key={`${blocker.action_type}-${blocker.skipped_reason}`}>
                {blocker.count} {formatAutopilotActionType(blocker.action_type)}:{" "}
                {formatAutopilotBlockerReason(blocker.skipped_reason)}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="gmail-worker-flags">
        <span className={status.ai_gmail_analysis_enabled ? "flag flag--ok" : "flag flag--warn"}>
          IA Gmail {status.ai_gmail_analysis_enabled ? "active" : "inactive"}
        </span>
        <span className={status.autopilot_followups_enabled ? "flag flag--ok" : "flag flag--warn"}>
          Relances {status.autopilot_followups_enabled ? "activees" : "desactivees"}
        </span>
        <span className={status.autopilot_appeals_enabled ? "flag flag--ok" : "flag flag--warn"}>
          Appels {status.autopilot_appeals_enabled ? "actifs" : "desactives"}
        </span>
        <span className={status.autopilot_initial_claims_enabled ? "flag flag--ok" : "flag flag--warn"}>
          Nouveaux dossiers {status.autopilot_initial_claims_enabled ? "automatiques" : "non automatiques"}
        </span>
        {status.autopilot_require_complete_restaurant_signature ? (
          <span className="flag flag--ok">Signature restaurant obligatoire</span>
        ) : null}
      </div>

      {cycle?.errors.length ? (
        <div className="gmail-worker-errors">
          {cycle.errors.map((error) => (
            <span key={error}>{error}</span>
          ))}
        </div>
      ) : null}
      {status.last_error ? <p className="muted">Derniere erreur sync: {status.last_error}</p> : null}
    </section>
  );
}

function GmailWorkerUnavailablePanel({ error }: { error: unknown }) {
  return (
    <section className="gmail-worker-card gmail-worker-card--attention">
      <div className="gmail-worker-card__header">
        <div>
          <p className="eyebrow">Gmail / IA 24-7</p>
          <h2>Statut Gmail indisponible</h2>
          <p>
            TENNET n'arrive pas a lire l'etat du worker Gmail depuis cette session. Ce bloc doit apparaitre au lieu de
            cacher le probleme.
          </p>
        </div>
        <StatusBadge status="manual_review" />
      </div>
      <div className="gmail-worker-grid">
        <div>
          <span>Controle</span>
          <strong>A verifier</strong>
          <small>{getErrorMessage(error)}</small>
        </div>
        <div>
          <span>Action</span>
          <strong>Reconnecter / verifier API</strong>
          <small>Si tu es connecte, cette erreur signale un vrai blocage API ou session.</small>
        </div>
      </div>
    </section>
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "Erreur inconnue pendant la lecture du statut Gmail.";
}

function formatAutopilotActionType(actionType: string) {
  const labels: Record<string, string> = {
    send_initial_claim: "nouveau dossier",
    send_followup_1: "relance",
    send_followup_2: "relance",
    send_escalation: "escalade",
    send_appeal: "appel/refus",
    request_more_evidence: "preuve",
    manual_review: "a verifier",
  };
  return labels[actionType] ?? actionType.replaceAll("_", " ");
}

function formatAutopilotBlockerReason(reason: string) {
  const labels: Record<string, string> = {
    missing_customer_name: "nom client manquant",
    missing_order_date: "date commande manquante",
    missing_order_identifier: "numero de commande manquant",
    missing_restaurant_name: "restaurant manquant",
    missing_restaurant_phone_number: "telephone restaurant manquant",
    missing_restaurant_email: "email restaurant manquant",
    missing_restaurant_address: "adresse restaurant manquante",
    missing_evidence: "preuve manquante",
    incomplete_evidence: "preuve incomplete",
    starred_gmail_thread_required: "fil Gmail etoile requis",
    same_template_without_new_argument: "pas de nouvel argument",
    cooldown_active: "delai de relance en cours",
    positive_gmail_payment_signal_detected: "paiement deja detecte dans Gmail",
    positive_payment_review_exists: "paiement deja comptabilise",
    daily_send_limit_reached: "limite quotidienne atteinte",
    per_restaurant_daily_limit_reached: "limite restaurant atteinte",
    initial_claims_disabled: "nouveaux dossiers automatiques desactives",
    manual_review_required: "verification humaine requise",
    recipient_not_matching_support_filter: "destinataire Uber non autorise",
    invalid_autopilot_recipient: "destinataire Uber invalide",
    gmail_account_not_connected: "Gmail non connecte",
    email_provider_disabled: "Gmail desactive",
  };
  return labels[reason] ?? reason.replaceAll("_", " ");
}

function RecoveryMachineFocusPanel({
  machine,
  filesByRail,
  runningRail,
  busy,
  onFilesChange,
}: {
  machine: RecoveryMachineResponse;
  filesByRail: Record<RecoveryMachineRailKey, File[]>;
  runningRail: RecoveryMachineRailKey | null;
  busy: boolean;
  onFilesChange: (railKey: RecoveryMachineRailKey, files: File[]) => void;
}) {
  const refunds = machine.rails.find((rail) => rail.key === "refunds");
  const cancellations = machine.rails.find((rail) => rail.key === "cancellations");
  const rails = [refunds, cancellations].filter(Boolean) as RecoveryMachineRail[];

  return (
    <section className="recovery-machine-focus" aria-label="Parcours de recuperation TENNET">
      <div className="machine-lane-grid">
        {rails.map((rail) => (
          <RecoveryMachineLane
            key={rail.key}
            rail={rail}
            files={filesByRail[rail.key]}
            running={runningRail === rail.key}
            disabled={busy || (runningRail !== null && runningRail !== rail.key)}
            onFilesChange={(files) => onFilesChange(rail.key, files)}
          />
        ))}
      </div>
      <div className="machine-snapshot machine-snapshot--compact">
        <MachineSnapshotItem label="Detecte" value={formatCurrency(machine.total_detected_amount)} />
        <MachineSnapshotItem label="Paiements confirmes" value={formatCurrency(machine.total_recovered_amount)} />
        <MachineSnapshotItem label="Actions ouvertes" value={machine.total_actions_count} />
      </div>
    </section>
  );
}

function MachineSnapshotItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RecoveryMachineLane({
  rail,
  files,
  running,
  disabled,
  onFilesChange,
}: {
  rail: RecoveryMachineRail;
  files: File[];
  running: boolean;
  disabled: boolean;
  onFilesChange: (files: File[]) => void;
}) {
  const evidenceNeeded = stageByKey(rail, "evidence_needed");
  const evidenceReceived = stageByKey(rail, "evidence_received");
  const uberEmails = stageByKey(rail, "uber_emails");
  const followups = stageByKey(rail, "followups");
  const payments = stageByKey(rail, "payments");
  const blockersCount = (evidenceNeeded?.count ?? 0) + (followups?.count ?? 0);
  const fileInputId = `home-${rail.key}-files`;
  const config =
    rail.key === "refunds"
      ? {
          instruction: "IMPORTEZ LES PREUVES DE DEMANDES DE REMBOURSEMENTS",
          helper:
            "Photos de ticket agrafe, PDF ou ZIP lies aux remboursements client. TENNET rattache au bon client, commande, restaurant et dossier.",
          fileButtonLabel: "Deposer preuves de remboursement",
        }
      : {
          instruction: "IMPORTEZ LES PREUVES DE DEMANDE D'ANNULATION",
          helper:
            "Photos de ticket agrafe, preuves terrain, PDF ou ZIP lies aux annulations. TENNET verifie paiement, doublons et preuves avant action.",
          fileButtonLabel: "Deposer preuves d'annulation",
        };

  return (
    <article className={`machine-lane machine-lane--${rail.health} machine-lane--home`}>
      <div className="machine-lane__top">
        <div>
          <span className="rail-kicker">{rail.short_title}</span>
          <h2>{rail.title}</h2>
          <p>{rail.description}</p>
        </div>
        <div
          className="rail-progress"
          aria-label={`${rail.progress_percent}%`}
          style={{ "--rail-progress": `${rail.progress_percent}%` } as CSSProperties}
        >
          <span>{rail.progress_percent}%</span>
        </div>
      </div>
      <div className="machine-lane__command">
        <div>
          <strong>{config.instruction}</strong>
          <p>{config.helper}</p>
          <small>
            {files.length > 0
              ? `${files.length} fichier(s) prets pour ce parcours.`
              : "Depose les preuves, puis TENNET lance le traitement complet automatiquement."}
          </small>
        </div>
        <div className="machine-lane__command-actions">
          <label className="button" htmlFor={fileInputId}>
            {config.fileButtonLabel}
          </label>
          <input
            id={fileInputId}
            className="machine-file-input"
            type="file"
            multiple
            accept={acceptedTypes}
            disabled={disabled || running}
            onChange={(event) => onFilesChange(Array.from(event.target.files ?? []))}
          />
          <span className="machine-auto-run-note">
            {running ? "TENNET travaille" : "Traitement automatique apres depot"}
          </span>
        </div>
      </div>
      <div className="machine-lane__amounts">
        <MachineSnapshotItem label="A recuperer" value={formatCurrency(rail.claimable_amount)} />
        <MachineSnapshotItem label="Recupere" value={formatCurrency(rail.recovered_amount)} />
        <MachineSnapshotItem label="Blocages reels" value={blockersCount} />
      </div>
      <div className="machine-lane__steps">
        <MachineLaneStep label="Preuves manquantes" stage={evidenceNeeded} />
        <MachineLaneStep label="Preuves recues" stage={evidenceReceived} />
        <MachineLaneStep label="Emails Uber" stage={uberEmails} />
        <MachineLaneStep label="Relances / appels" stage={followups} />
        <MachineLaneStep label="Paiements confirmes" stage={payments} />
      </div>
      <div className="machine-lane__bottom">
        <p>{laneStatusText(rail, blockersCount)}</p>
        <Link href={rail.next_action_href} className="secondary-button">
          {rail.next_action_label}
        </Link>
      </div>
    </article>
  );
}

function MachineLaneStep({ label, stage }: { label: string; stage?: RecoveryMachineStage }) {
  if (!stage) {
    return null;
  }
  return (
    <Link href={stage.href} className={`machine-step machine-step--${stage.status}`}>
      <span>{label}</span>
      <strong>{stage.count}</strong>
      <small>{formatCurrency(stage.amount)}</small>
    </Link>
  );
}

function stageByKey(rail: RecoveryMachineRail, key: RecoveryMachineStage["key"]): RecoveryMachineStage | undefined {
  return rail.stages.find((stage) => stage.key === key);
}

function laneStatusText(rail: RecoveryMachineRail, blockersCount: number): string {
  if (blockersCount > 0) {
    return `${blockersCount} blocage(s) avec raison visible. TENNET ne fabrique rien sans preuve fiable.`;
  }
  if (rail.detected_count === 0) {
    return "Aucun dossier detecte pour ce parcours. Depose les fichiers, TENNET lance la lecture.";
  }
  if (rail.recovered_count > 0) {
    return "Parcours actif : les paiements confirmes sont deja comptabilises.";
  }
  return "Parcours pret : TENNET continue les emails, relances et controles autorises.";
}

function RecoveryRailStage({ stage }: { stage: RecoveryMachineStage }) {
  return (
    <Link href={stage.href} className={`rail-stage rail-stage--${stage.status}`}>
      <div>
        <strong>{stage.label}</strong>
        <span>{stage.description}</span>
      </div>
      <small>
        {stage.count} · {formatCurrency(stage.amount)}
      </small>
    </Link>
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
    historical_reclassification: "Restaurants corriges",
    historical_import_repair: "Imports repares",
    deductions: "Deductions",
    claim_orders: "Dossiers",
    smart_import_recovery: "Fichiers repris",
    unclassified: "Non classes",
    drafts: "Brouillons",
    followups: "Relances",
    appeals: "Appels",
    gmail_sync: "Gmail",
    autopilot: "AutoPilot",
  };
  return labels[name] ?? name;
}

function UnclassifiedPanel({ unclassified }: { unclassified: WorkspaceUnclassifiedResponse }) {
  return (
    <section className="tool-panel tool-panel--warning">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Non classes</p>
          <h2>{unclassified.total_count} source(s) a completer</h2>
          <p className="muted">
            TENNET ne bloque pas ces fichiers : il te dit ce qui manque, tu ajoutes la preuve ou l'explication, puis la
            machine reprend automatiquement.
          </p>
        </div>
        <Link href="/smart-import" className="secondary-button">
          Deposer preuves
        </Link>
      </div>
      <div className="premium-card-grid">
        {unclassified.items.slice(0, 6).map((item) => (
          <article key={`${item.source_type}-${item.source_id}`} className="premium-card premium-card--warning">
            <h3>{item.title}</h3>
            <p className="muted">{item.original_filename}</p>
            <p>{item.description}</p>
            {item.missing_fields.length > 0 ? (
              <div className="chip-list">
                {item.missing_fields.map((field) => (
                  <span key={field} className="chip">
                    {field}
                  </span>
                ))}
              </div>
            ) : null}
            <Link href={item.action_url} className="button">
              Corriger
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
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

function formatDuration(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "-";
  }
  if (totalSeconds < 60) {
    return `${Math.round(totalSeconds)} s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.round(totalSeconds % 60);
  if (minutes < 60) {
    return seconds > 0 ? `${minutes} min ${seconds} s` : `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes > 0 ? `${hours} h ${remainingMinutes} min` : `${hours} h`;
}

function formatPercent(value: string | number | null): string {
  const numericValue = typeof value === "number" ? value : Number(value ?? 0);
  return `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format(numericValue * 100)} %`;
}
