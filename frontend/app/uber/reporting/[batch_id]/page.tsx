"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  type UberReportingConfirmResponse,
  type UberReportingImportBatch,
  type UberReportingImportRow,
  type UberReportingRowStatus,
} from "@/lib/api";

type PageProps = { params: Promise<{ batch_id: string }> };

const rowStatuses: UberReportingRowStatus[] = ["valid", "invalid", "warning", "duplicate", "created", "skipped"];

export default function UberReportingBatchPage({ params }: PageProps) {
  const { batch_id: batchIdParam } = use(params);
  const batchId = Number(batchIdParam);
  const [batch, setBatch] = useState<UberReportingImportBatch | null>(null);
  const [rows, setRows] = useState<UberReportingImportRow[]>([]);
  const [statusFilter, setStatusFilter] = useState<UberReportingRowStatus | "">("");
  const [result, setResult] = useState<UberReportingConfirmResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);

  const loadData = useCallback(async () => {
    const [batchData, rowsData] = await Promise.all([
      api.getUberReportingBatch(batchId),
      api.getUberReportingRows(batchId, { status: statusFilter, limit: 200 }),
    ]);
    setBatch(batchData);
    setRows(rowsData.rows);
  }, [batchId, statusFilter]);

  useEffect(() => {
    loadData().catch(setError).finally(() => setLoading(false));
  }, [loadData]);

  async function runAction(action: "confirm" | "cancel") {
    setWorking(true);
    setError(null);
    try {
      if (action === "confirm") {
        setResult(await api.confirmUberReportingBatch(batchId));
      } else {
        await api.cancelUberReportingBatch(batchId);
      }
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement batch Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Detail import reporting</h1>
        </div>
        <div className="action-row">
          <button type="button" className="button" onClick={() => runAction("confirm")} disabled={working || batch?.status !== "parsed"}>
            Confirmer import
          </button>
          <button type="button" className="secondary-button" onClick={() => runAction("cancel")} disabled={working || batch?.status !== "parsed"}>
            Annuler
          </button>
        </div>
      </div>
      <ApiError error={error} />
      {batch ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>{batch.original_filename}</h2>
            <StatusBadge status={batch.status} />
          </div>
          <div className="detail-grid">
            <DetailItem label="Type" value={batch.report_type} />
            <DetailItem label="Total lignes" value={String(batch.total_rows)} />
            <DetailItem label="Valides" value={String(batch.valid_rows)} />
            <DetailItem label="Invalides" value={String(batch.invalid_rows)} />
            <DetailItem label="Warnings" value={String(batch.warning_rows)} />
            <DetailItem label="Doublons" value={String(batch.duplicate_rows)} />
          </div>
          {result ? (
            <p>
              {result.created_snapshots_count} snapshot(s), {result.created_transactions_count} transaction(s), {result.skipped_rows} ignoree(s)
            </p>
          ) : null}
          <Link className="secondary-button" href="/uber/unmapped-stores">Voir stores non mappes</Link>
        </section>
      ) : null}
      <section className="tool-panel">
        <div className="field">
          <label htmlFor="row_status">Filtre lignes</label>
          <select id="row_status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as UberReportingRowStatus | "")}>
            <option value="">Toutes</option>
            {rowStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </div>
      </section>
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ligne</th>
                <th>Statut</th>
                <th>Commande</th>
                <th>Store</th>
                <th>Erreurs</th>
                <th>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.row_number}</td>
                  <td><StatusBadge status={row.status} /></td>
                  <td>{String(row.normalized_data?.uber_order_id ?? "-")}</td>
                  <td>{String(row.normalized_data?.uber_store_id ?? "-")}</td>
                  <td>{row.errors.join(", ") || "-"}</td>
                  <td>{row.warnings.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune ligne" />
      )}
    </section>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
