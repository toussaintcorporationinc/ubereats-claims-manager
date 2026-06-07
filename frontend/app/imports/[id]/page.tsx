"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type ImportBatch,
  type ImportConfirmResponse,
  type ImportRow,
  type ImportRowStatus,
} from "@/lib/api";

const rowStatuses: Array<ImportRowStatus | ""> = ["", "valid", "invalid", "duplicate", "unauthorized", "created", "skipped"];
const finalStatuses = new Set(["confirmed", "partially_imported", "failed", "cancelled"]);

export default function ImportDetailPage() {
  const params = useParams<{ id: string }>();
  const batchId = Number(params.id);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [statusFilter, setStatusFilter] = useState<ImportRowStatus | "">("");
  const [confirmResult, setConfirmResult] = useState<ImportConfirmResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const loadImport = useCallback(async () => {
    const [batchData, rowsData] = await Promise.all([
      api.getImportBatch(batchId),
      api.getImportRows(batchId, { status: statusFilter, limit: 200 }),
    ]);
    setBatch(batchData);
    setRows(rowsData.rows);
  }, [batchId, statusFilter]);

  useEffect(() => {
    if (!Number.isFinite(batchId)) {
      setError(new Error("Import invalide"));
      setLoading(false);
      return;
    }

    loadImport()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [batchId, loadImport]);

  async function handleConfirm() {
    setConfirming(true);
    setActionError(null);
    setConfirmResult(null);

    try {
      const result = await api.confirmImportBatch(batchId);
      setConfirmResult(result);
      await loadImport();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setConfirming(false);
    }
  }

  async function handleCancel() {
    setCancelling(true);
    setActionError(null);

    try {
      await api.cancelImportBatch(batchId);
      await loadImport();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setCancelling(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement de l'import" />;
  }

  if (!batch) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Import introuvable" />
      </section>
    );
  }

  const canAct = !finalStatuses.has(batch.status);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Import</p>
          <h1>{batch.original_filename}</h1>
        </div>
        <div className="actions">
          <Link href="/imports" className="secondary-button">
            Retour imports
          </Link>
          {canAct ? (
            <>
              <button type="button" className="button" onClick={handleConfirm} disabled={confirming}>
                {confirming ? "Confirmation" : "Confirmer import"}
              </button>
              <button type="button" className="danger-button" onClick={handleCancel} disabled={cancelling}>
                {cancelling ? "Annulation" : "Annuler import"}
              </button>
            </>
          ) : null}
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      {confirmResult ? (
        <div className="success-box">
          <strong>Import confirme</strong>
          <span>
            {confirmResult.created_orders_count} commandes creees, {confirmResult.skipped_rows} lignes ignorees.
          </span>
        </div>
      ) : null}

      <div className="stats-grid">
        <StatCard label="Total lignes" value={batch.total_rows} />
        <StatCard label="Valides" value={batch.valid_rows} />
        <StatCard label="Invalides" value={batch.invalid_rows} />
        <StatCard label="Doublons" value={batch.duplicate_rows} />
        <StatCard label="Creees" value={batch.created_orders_count} />
      </div>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Resume</h2>
          <StatusBadge status={batch.status} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Type fichier" value={batch.file_type} />
          <DetailItem label="Non autorisees" value={String(batch.unauthorized_rows)} />
          <DetailItem label="Cree le" value={formatDate(batch.created_at)} />
          <DetailItem label="Confirme le" value={formatDate(batch.confirmed_at)} />
        </div>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Lignes</h2>
          <div className="field">
            <label htmlFor="row_status_filter">Statut</label>
            <select
              id="row_status_filter"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as ImportRowStatus | "")}
            >
              {rowStatuses.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "Tous"}
                </option>
              ))}
            </select>
          </div>
        </div>

        {rows.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ligne</th>
                  <th>Statut</th>
                  <th>Commande Uber</th>
                  <th>Restaurant</th>
                  <th>Montant</th>
                  <th>Erreurs</th>
                  <th>Warnings</th>
                  <th>Commande creee</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td>{readNormalized(row, "uber_order_number")}</td>
                    <td>{readNormalized(row, "restaurant_id")}</td>
                    <td>{readNormalized(row, "order_amount")}</td>
                    <td>{formatList(row.errors)}</td>
                    <td>{formatList(row.warnings)}</td>
                    <td>
                      {row.created_order_id ? (
                        <Link href={`/orders/${row.created_order_id}`} className="secondary-button">
                          Ouvrir
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Aucune ligne" />
        )}
      </section>
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

function readNormalized(row: ImportRow, key: string): string {
  const value = row.normalized_data?.[key];
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatList(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "-";
}
