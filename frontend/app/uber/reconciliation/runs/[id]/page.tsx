"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  type UberReconciliationResult,
  type UberReconciliationRun,
  type UberReconciliationStatus,
} from "@/lib/api";

const statusOptions: Array<UberReconciliationStatus | ""> = [
  "",
  "not_compensated",
  "partially_compensated",
  "needs_evidence",
  "already_claimed",
  "manual_review",
  "compensated",
  "ignored",
];

export default function UberReconciliationRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = Number(params.id);
  const [run, setRun] = useState<UberReconciliationRun | null>(null);
  const [results, setResults] = useState<UberReconciliationResult[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [statusFilter, setStatusFilter] = useState<UberReconciliationStatus | "">("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  async function loadData() {
    const [runData, resultData] = await Promise.all([
      api.getUberReconciliationRun(runId),
      api.getUberReconciliationResults({ run_id: runId, status: statusFilter, limit: 500 }),
    ]);
    setRun(runData);
    setResults(resultData.results);
  }

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, statusFilter]);

  const eligibleIds = useMemo(
    () =>
      results
        .filter((result) => ["not_compensated", "partially_compensated", "needs_evidence"].includes(result.status) && !result.claim_order_id)
        .map((result) => result.id),
    [results],
  );

  function toggleSelected(resultId: number) {
    setSelected((current) => (current.includes(resultId) ? current.filter((id) => id !== resultId) : [...current, resultId]));
  }

  async function createClaim(resultId: number) {
    setWorking(true);
    setError(null);
    try {
      await api.createClaimOrderFromUberResult(resultId);
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  async function bulkCreate() {
    setWorking(true);
    setError(null);
    try {
      await api.bulkCreateClaimOrdersFromUberResults(selected);
      setSelected([]);
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  async function ignoreResult(resultId: number) {
    setWorking(true);
    setError(null);
    try {
      await api.ignoreUberReconciliationResult(resultId, "Ignore depuis l'interface de reconciliation");
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  if (loading || !run) {
    return <LoadingState label="Chargement analyse Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Analyse #{run.id}</h1>
          <p>Aucune contestation ni email n&apos;est cree automatiquement.</p>
        </div>
        <Link className="secondary-button" href="/uber/reconciliation/runs">
          Retour analyses
        </Link>
      </div>
      <ApiError error={error} />
      <div className="stats-grid">
        <StatCard label="Commandes" value={run.total_orders_analyzed} />
        <StatCard label="Annulees" value={run.canceled_orders_count} />
        <StatCard label="Non compensees" value={run.not_compensated_count} />
        <StatCard label="Partielles" value={run.partially_compensated_count} />
        <StatCard label="Besoin preuve" value={run.needs_evidence_count} />
        <StatCard label="Revue manuelle" value={run.manual_review_count} />
        <StatCard label="Manquant" value={formatCurrency(run.total_missing_amount)} />
      </div>
      <div className="inline-form">
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as UberReconciliationStatus | "")}>
          {statusOptions.map((status) => (
            <option key={status || "all"} value={status}>
              {status || "Tous statuts"}
            </option>
          ))}
        </select>
        <button type="button" className="button" disabled={working || selected.length === 0} onClick={bulkCreate}>
          Creer dossiers selectionnes
        </button>
        <button type="button" className="secondary-button" onClick={() => setSelected(eligibleIds)} disabled={eligibleIds.length === 0}>
          Selectionner eligibles
        </button>
      </div>
      {results.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th>Commande Uber</th>
                <th>Statut</th>
                <th>Montant</th>
                <th>Paye</th>
                <th>Manquant</th>
                <th>Raison</th>
                <th>Preuve</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => {
                const eligible = eligibleIds.includes(result.id);
                return (
                  <tr key={result.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selected.includes(result.id)}
                        disabled={!eligible}
                        onChange={() => toggleSelected(result.id)}
                      />
                    </td>
                    <td>{result.display_id || result.uber_order_id}</td>
                    <td>
                      <StatusBadge status={result.status} />
                    </td>
                    <td>{formatCurrency(result.order_amount, result.currency)}</td>
                    <td>{formatCurrency(result.paid_amount, result.currency)}</td>
                    <td>{formatCurrency(result.missing_amount, result.currency)}</td>
                    <td>{result.reason}</td>
                    <td>{result.evidence_required ? "requise" : "-"}</td>
                    <td>
                      {result.claim_order_id ? (
                        <Link className="secondary-button" href={`/orders/${result.claim_order_id}`}>
                          Dossier
                        </Link>
                      ) : eligible ? (
                        <button type="button" className="button" disabled={working} onClick={() => createClaim(result.id)}>
                          Creer dossier
                        </button>
                      ) : (
                        <button type="button" className="secondary-button" disabled={working || result.status === "ignored"} onClick={() => ignoreResult(result.id)}>
                          Ignorer
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun resultat" />
      )}
    </section>
  );
}
