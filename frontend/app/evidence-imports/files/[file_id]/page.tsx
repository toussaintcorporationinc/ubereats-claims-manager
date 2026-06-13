"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type EvidenceImportedFileDetail,
  type EvidenceMatchCandidate,
} from "@/lib/api";

type PageProps = { params: Promise<{ file_id: string }> };

export default function EvidenceImportedFilePage({ params }: PageProps) {
  const { file_id: fileIdParam } = use(params);
  const fileId = Number(fileIdParam);
  const [detail, setDetail] = useState<EvidenceImportedFileDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    setDetail(await api.getEvidenceImportedFile(fileId));
  }, [fileId]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function runAction(action: string, callback: () => Promise<unknown>) {
    setWorking(action);
    setError(null);
    try {
      await callback();
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setWorking(null);
    }
  }

  async function downloadPreview() {
    await runAction("preview", async () => {
      const blob = await api.previewEvidenceImportedFile(fileId);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener,noreferrer");
    });
  }

  if (loading) {
    return <LoadingState label="Chargement fichier preuve" />;
  }

  const latestAnalysis = detail?.analysis_results[0] ?? null;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuves</p>
          <h1>{detail?.file.original_filename ?? "Fichier importe"}</h1>
        </div>
        <div className="actions">
          <button type="button" className="secondary-button" onClick={downloadPreview} disabled={working === "preview"}>
            Apercu
          </button>
          {detail ? (
            <Link href={`/evidence-imports/${detail.file.batch_id}`} className="secondary-button">
              Batch
            </Link>
          ) : null}
        </div>
      </div>

      <ApiError error={error} />

      {detail ? (
        <>
          {detail.file.status === "ignored" ? (
            <div className="success-box">
              <strong>Doublon exact verifie</strong>
              <span>
                TENNET n'a pas retraite cette copie : le fichier canonique est deja conserve. L'apercu ouvre la preuve
                conservee pour controle.
              </span>
            </div>
          ) : null}

          <section className="tool-panel">
            <div className="section-heading">
              <h2>Analyse</h2>
              <StatusBadge status={detail.file.status} />
            </div>
            {latestAnalysis ? (
              <div className="grid-two">
                <div>
                  <p>Type detecte : <strong>{latestAnalysis.detected_evidence_type}</strong></p>
                  <p>Commande : <strong>{latestAnalysis.detected_uber_order_number ?? latestAnalysis.detected_display_id ?? "-"}</strong></p>
                  <p>Montant : <strong>{formatCurrency(latestAnalysis.detected_order_amount, latestAnalysis.detected_currency ?? "EUR")}</strong></p>
                  <p>Date : <strong>{formatDate(latestAnalysis.detected_order_date)}</strong></p>
                </div>
                <div>
                  <p>Classification : {latestAnalysis.classification_confidence}</p>
                  <p>Extraction : {latestAnalysis.extraction_confidence}</p>
                  <p>Matching : {latestAnalysis.matching_confidence}</p>
                </div>
              </div>
            ) : (
              <EmptyState title="Aucune analyse disponible" />
            )}
          </section>

          <section className="tool-panel">
            <h2>Candidats</h2>
            {detail.candidates.length === 0 ? (
              <EmptyState title="Aucun candidat propose" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Cible</th>
                      <th>Raison</th>
                      <th>Score</th>
                      <th>Statut</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {detail.candidates.map((candidate) => (
                      <CandidateRow
                        key={candidate.id}
                        candidate={candidate}
                        disabled={Boolean(working)}
                        onAccept={() => runAction(`accept-${candidate.id}`, () => api.acceptEvidenceMatchCandidate(candidate.id))}
                        onReject={() => runAction(`reject-${candidate.id}`, () => api.rejectEvidenceMatchCandidate(candidate.id, "Rejete manuellement"))}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <button
              type="button"
              className="danger-button"
              disabled={Boolean(working) || detail.file.status === "ignored"}
              onClick={() => runAction("ignore", () => api.ignoreEvidenceImportedFile(fileId, "Ignore manuellement"))}
            >
              Ignorer ce fichier
            </button>
          </section>
        </>
      ) : null}
    </section>
  );
}

function CandidateRow({
  candidate,
  disabled,
  onAccept,
  onReject,
}: {
  candidate: EvidenceMatchCandidate;
  disabled: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <tr>
      <td>{candidate.candidate_type} #{candidate.candidate_id}</td>
      <td>{candidate.match_reason}</td>
      <td>{candidate.match_score}</td>
      <td>
        <StatusBadge status={candidate.status} />
      </td>
      <td>
        <div className="actions">
          <button type="button" className="button" disabled={disabled || candidate.status === "accepted"} onClick={onAccept}>
            Accepter
          </button>
          <button type="button" className="secondary-button" disabled={disabled || candidate.status === "rejected"} onClick={onReject}>
            Rejeter
          </button>
        </div>
      </td>
    </tr>
  );
}
