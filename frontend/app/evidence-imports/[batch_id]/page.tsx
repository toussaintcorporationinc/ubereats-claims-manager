"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type EvidenceAnalysisProvider,
  type EvidenceImportAnalyzeResponse,
  type EvidenceImportBatch,
  type EvidenceImportedFile,
  type EvidenceImportedFileStatus,
} from "@/lib/api";

type PageProps = { params: Promise<{ batch_id: string }> };
const statuses: Array<EvidenceImportedFileStatus | ""> = ["", "analysis_pending", "analyzed", "failed", "ignored"];

export default function EvidenceImportBatchPage({ params }: PageProps) {
  const { batch_id: batchIdParam } = use(params);
  const batchId = Number(batchIdParam);
  const [batch, setBatch] = useState<EvidenceImportBatch | null>(null);
  const [files, setFiles] = useState<EvidenceImportedFile[]>([]);
  const [statusFilter, setStatusFilter] = useState<EvidenceImportedFileStatus | "">("");
  const [provider, setProvider] = useState<EvidenceAnalysisProvider>("fake");
  const [result, setResult] = useState<EvidenceImportAnalyzeResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    const [batchData, filesData] = await Promise.all([
      api.getEvidenceImport(batchId),
      api.getEvidenceImportFiles(batchId, { status: statusFilter, limit: 200 }),
    ]);
    setBatch(batchData);
    setFiles(filesData.files);
  }, [batchId, statusFilter]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function runAction(action: "analyze" | "bulk") {
    setWorking(action);
    setError(null);
    try {
      const actionResult =
        action === "analyze"
          ? await api.analyzeEvidenceImport(batchId, { provider, limit: 100 })
          : await api.bulkAcceptEvidenceImport(batchId, { min_score: "0.90" });
      if ("batch_id" in actionResult) {
        setResult(actionResult);
      }
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement import preuves" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuves</p>
          <h1>Import #{batchId}</h1>
        </div>
        <Link href="/evidence-imports" className="secondary-button">
          Retour
        </Link>
      </div>

      <ApiError error={error} />

      {batch ? (
        <>
          <div className="stats-grid">
            <StatCard label="Fichiers" value={batch.total_files} />
            <StatCard label="Stockes" value={batch.stored_files_count} />
            <StatCard label="Analyses" value={batch.analyzed_files_count} />
            <StatCard label="A revoir" value={batch.needs_review_count} />
            <StatCard label="Doublons supprimes" value={batch.duplicate_files_count} />
            <StatCard label="Echecs" value={batch.failed_files_count} />
          </div>

          {batch.duplicate_files_count > 0 ? (
            <div className="success-box">
              <strong>Doublons traites</strong>
              <span>
                TENNET a conserve le fichier canonique et retire {batch.duplicate_files_count} copie(s) exacte(s)
                apres verification checksum. Les doublons restent visibles ci-dessous avec le statut ignore.
              </span>
            </div>
          ) : null}

          <section className="tool-panel">
            <div className="section-heading">
              <h2>Analyse</h2>
              <StatusBadge status={batch.status} />
            </div>
            <div className="filters">
              <div className="field">
                <label htmlFor="provider">Provider</label>
                <select id="provider" value={provider} onChange={(event) => setProvider(event.target.value as EvidenceAnalysisProvider)}>
                  <option value="fake">fake</option>
                  <option value="local_ocr">local_ocr</option>
                  <option value="openai_vision">openai_vision</option>
                </select>
              </div>
              <button type="button" className="button" disabled={working === "analyze"} onClick={() => runAction("analyze")}>
                Analyser
              </button>
              <button type="button" className="secondary-button" disabled={working === "bulk"} onClick={() => runAction("bulk")}>
                Accepter haute confiance
              </button>
            </div>
            {result ? (
              <div className="success-box">
                Analyse terminee : {result.analyzed_files_count} fichier(s), {result.needs_review_count} a revoir.
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Fichiers</h2>
          <div className="field inline-form">
            <label htmlFor="status_filter">Statut</label>
            <select id="status_filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as EvidenceImportedFileStatus | "")}>
              {statuses.map((status) => (
                <option key={status || "all"} value={status}>
                  {status || "Tous"}
                </option>
              ))}
            </select>
          </div>
        </div>
        {files.length === 0 ? (
          <EmptyState
            title={batch?.duplicate_files_count ? "Doublons deja traites" : "Aucun fichier"}
            description={
              batch?.duplicate_files_count
                ? "Ce batch ancien ne contient que des doublons retires. Les prochains imports afficheront chaque doublon verifie dans cette liste."
                : undefined
            }
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fichier</th>
                  <th>Type</th>
                  <th>Taille</th>
                  <th>Statut</th>
                  <th>Date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {files.map((file) => (
                  <tr key={file.id}>
                    <td>
                      {file.original_filename}
                      {file.status === "ignored" ? <div className="muted">Doublon exact conserve ailleurs</div> : null}
                    </td>
                    <td>{file.status === "ignored" ? "Doublon verifie" : file.mime_type ?? "-"}</td>
                    <td>{formatBytes(file.file_size)}</td>
                    <td>
                      <StatusBadge status={file.status} />
                    </td>
                    <td>{formatDate(file.created_at)}</td>
                    <td>
                      <Link href={`/evidence-imports/files/${file.id}`} className="secondary-button">
                        {file.status === "ignored" ? "Comprendre" : "Revoir"}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} o`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} Ko`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} Mo`;
}
