"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  type UberReconciliationResult,
  type UberReconciliationRunResponse,
  type UberReportingImportResponse,
} from "@/lib/api";

export default function UberReconciliationPage() {
  const [results, setResults] = useState<UberReconciliationResult[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [importResult, setImportResult] = useState<UberReportingImportResponse | null>(null);
  const [runResult, setRunResult] = useState<UberReconciliationRunResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  async function loadResults() {
    const data = await api.getUberReconciliationResults({ limit: 200 });
    setResults(data.results);
  }

  useEffect(() => {
    loadResults()
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleImport() {
    if (!file) {
      setError(new Error("Selectionnez un rapport CSV ou XLSX."));
      return;
    }
    setWorking(true);
    setError(null);
    try {
      const result = await api.importUberReporting(file);
      setImportResult(result);
      await loadResults();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  async function handleRun() {
    setWorking(true);
    setError(null);
    try {
      const result = await api.runUberReconciliation();
      setRunResult(result);
      await loadResults();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  async function handleCreateClaim(resultId: number) {
    setWorking(true);
    setError(null);
    try {
      await api.createClaimOrderFromUberResult(resultId);
      await loadResults();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement reconciliation Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Reconciliation financiere</h1>
        </div>
        <button type="button" className="button" onClick={handleRun} disabled={working}>
          Lancer reconciliation
        </button>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Import rapport Uber Eats Manager</h2>
          <StatusBadge status="manager_export" />
        </div>
        <div className="inline-form">
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] ?? null)}
          />
          <button type="button" className="secondary-button" onClick={handleImport} disabled={working}>
            Importer
          </button>
        </div>
        {importResult ? (
          <p>
            {importResult.snapshots_created} commande(s), {importResult.transactions_created} transaction(s),{" "}
            {importResult.rows_skipped} ligne(s) ignoree(s)
          </p>
        ) : null}
        {runResult ? (
          <p>
            {runResult.results_created} resultat(s) cree(s), {runResult.results_updated} mis a jour,{" "}
            {runResult.ignored_orders} ignore(s)
          </p>
        ) : null}
      </section>

      {results.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Commande Uber</th>
                <th>Statut</th>
                <th>Montant commande</th>
                <th>Paye</th>
                <th>Rembourse</th>
                <th>Manquant</th>
                <th>Raison</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr key={result.id}>
                  <td>{result.uber_order_id}</td>
                  <td>
                    <StatusBadge status={result.status} />
                  </td>
                  <td>{formatCurrency(result.order_amount)}</td>
                  <td>{formatCurrency(result.paid_amount)}</td>
                  <td>{formatCurrency(result.refunded_amount)}</td>
                  <td>{formatCurrency(result.missing_amount)}</td>
                  <td>{result.reason}</td>
                  <td>
                    {result.claim_order_id ? (
                      <Link className="secondary-button" href={`/orders/${result.claim_order_id}`}>
                        Ouvrir dossier
                      </Link>
                    ) : (
                      <button
                        type="button"
                        className="button"
                        disabled={!["not_compensated", "partially_compensated", "needs_evidence"].includes(result.status) || working}
                        onClick={() => handleCreateClaim(result.id)}
                      >
                        Creer dossier TENNET
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun resultat de reconciliation" />
      )}
    </section>
  );
}
