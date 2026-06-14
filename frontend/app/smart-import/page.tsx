"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import MobileActionBar from "@/components/MobileActionBar";
import PremiumEmptyState from "@/components/PremiumEmptyState";
import SmartImportPreviewCard from "@/components/SmartImportPreviewCard";
import {
  api,
  type Restaurant,
  type SmartImportConfirmResponse,
  type SmartImportFileDecision,
  type SmartImportPreviewResponse,
  type SmartImportRecommendedAction,
  type UberReportingReportType,
} from "@/lib/api";

const acceptedTypes = ".csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.zip,image/*,application/pdf";

export default function SmartImportPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<SmartImportPreviewResponse | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [decisions, setDecisions] = useState<Record<number, SmartImportFileDecision>>({});
  const [confirmResult, setConfirmResult] = useState<SmartImportConfirmResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    api
      .getRestaurants()
      .then(setRestaurants)
      .catch(() => setRestaurants([]));
  }, []);

  async function handlePreview() {
    if (files.length === 0) {
      setError(new Error("Ajoutez au moins un fichier."));
      return;
    }
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.previewSmartImport(files);
      setPreview(result);
      setConfirmResult(null);
      const recommendedDecisions: Record<number, SmartImportFileDecision> = Object.fromEntries(
        result.files.map((file) => [
          file.id,
          {
            file_id: file.id,
            action: file.recommended_action,
            report_type: file.detected_report_type ?? "combined_report",
            restaurant_id: null,
          },
        ]),
      );
      setDecisions(recommendedDecisions);
      const confirmResponse = await api.confirmSmartImport(result.batch_preview_id, Object.values(recommendedDecisions));
      setConfirmResult(confirmResponse);
      setPreview((current) => (current ? { ...current, status: confirmResponse.status } : current));
      setSuccess(
        `TENNET a traite ${confirmResponse.routed_files.length} fichier(s), garde ${confirmResponse.manual_review_files.length} a verifier et ignore ${confirmResponse.ignored_files.length} doublon(s).`,
      );
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!preview) {
      return;
    }
    setConfirming(true);
    setError(null);
    try {
      const result = await api.confirmSmartImport(preview.batch_preview_id, Object.values(decisions));
      setConfirmResult(result);
      setSuccess(`Smart Import confirme : ${result.routed_files.length} fichier(s) route(s).`);
      setPreview((current) => (current ? { ...current, status: result.status } : current));
    } catch (apiError) {
      setError(apiError);
    } finally {
      setConfirming(false);
    }
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Smart Import</p>
          <h1>Deposer sans renommer</h1>
          <p>TENNET lit le contenu, classe les fichiers, applique les imports Uber surs et range les preuves.</p>
        </div>
      </div>

      <ApiError error={error} />
      {success ? <div className="success-box">{success}</div> : null}

      <section className="smart-import-steps" aria-label="Fonctionnement Smart Import">
        <article className="smart-step">
          <span>1</span>
          <strong>Depose</strong>
          <p>CSV, XLSX, PDF, image ou ZIP. Le nom du fichier n'a pas besoin d'etre propre.</p>
        </article>
        <article className="smart-step">
          <span>2</span>
          <strong>TENNET detecte</strong>
          <p>Rapport Uber, paiement, ajustement, preuve ou fichier a verifier.</p>
        </article>
        <article className="smart-step">
          <span>3</span>
          <strong>TENNET traite</strong>
          <p>Les rapports surs sont appliques. Les preuves sont rangees. Les doutes restent a verifier.</p>
        </article>
      </section>

      {confirmResult ? (
        <section className="tool-panel">
          <div className="section-heading">
            <div>
              <h2>Resultat Smart Import</h2>
              <p className="muted">
                {confirmResult.routed_files.length} workflow(s) cree(s), {confirmResult.manual_review_files.length} a verifier,{" "}
                {confirmResult.ignored_files.length} doublon(s) ou fichier(s) ignore(s).
              </p>
            </div>
            <div className="actions">
              {hasDestination(confirmResult, "uber_reporting_batch") ? (
                <Link className="button" href="/uber/reporting">
                  Voir les imports Uber
                </Link>
              ) : null}
              {hasDestination(confirmResult, "evidence_import_batch") ? (
                <Link className="secondary-button" href="/evidence-imports">
                  Voir les imports preuves
                </Link>
              ) : null}
            </div>
          </div>
          <div className="simple-callout">
            <strong>Prochaine etape</strong>
            {hasDestination(confirmResult, "uber_reporting_batch") ? (
              <p>
                TENNET a cree les commandes/transactions possibles. Ouvre le detail seulement pour voir les lignes
                bloquees ou les erreurs.
              </p>
            ) : null}
            {hasDestination(confirmResult, "evidence_import_batch") ? (
              <p>
                Les preuves sont rangees et analysees localement. Les rattachements douteux restent a verifier.
              </p>
            ) : null}
            {!hasDestination(confirmResult, "uber_reporting_batch") && !hasDestination(confirmResult, "evidence_import_batch") ? (
              <p>Les fichiers douteux restent conserves en revue. Rien n'est supprime brutalement.</p>
            ) : null}
          </div>
          <div className="premium-card-grid">
            {confirmResult.routed_files.map((file) => (
              <article key={`${file.file_id}-${file.destination_type}`} className="premium-card">
                <h3>{file.original_filename}</h3>
                <p className="muted">{labelForDestination(file)}</p>
                <div className="detail-grid detail-grid--compact">
                  {file.destination_type === "uber_reporting_batch" ? (
                    <>
                      <div className="detail-item">
                        <span>Commandes</span>
                        <strong>{file.created_snapshots_count ?? 0}</strong>
                      </div>
                      <div className="detail-item">
                        <span>Transactions</span>
                        <strong>{file.created_transactions_count ?? 0}</strong>
                      </div>
                      <div className="detail-item">
                        <span>Bloquees</span>
                        <strong>{file.skipped_rows ?? 0}</strong>
                      </div>
                    </>
                  ) : null}
                  {file.destination_type === "evidence_import_batch" ? (
                    <>
                      <div className="detail-item">
                        <span>Analysees</span>
                        <strong>{file.analyzed_files_count ?? 0}</strong>
                      </div>
                      <div className="detail-item">
                        <span>Matches</span>
                        <strong>{file.auto_matched_count ?? 0}</strong>
                      </div>
                      <div className="detail-item">
                        <span>A verifier</span>
                        <strong>{file.needs_review_count ?? 0}</strong>
                      </div>
                    </>
                  ) : null}
                </div>
                {file.processing_errors.length > 0 ? <p className="muted">A verifier : {file.processing_errors.join(", ")}</p> : null}
                {file.destination_url ? (
                  <Link className="button" href={file.destination_url}>
                    Ouvrir le detail
                  </Link>
                ) : null}
              </article>
            ))}
            {confirmResult.manual_review_files.map((file) => (
              <article key={`manual-${file.file_id}`} className="premium-card">
                <h3>{file.original_filename}</h3>
                <p className="muted">Fichier garde pour revue manuelle.</p>
              </article>
            ))}
            {confirmResult.ignored_files.map((file) => (
              <article key={`ignored-${file.file_id}`} className="premium-card">
                <h3>{file.original_filename}</h3>
                <p className="muted">
                  {file.destination_type === "duplicate_ignored" ? "Doublon exact traite. TENNET garde le fichier canonique." : "Fichier ignore."}
                </p>
              </article>
            ))}
            {confirmResult.errors.map((item) => (
              <article key={`error-${item.file_id}`} className="premium-card">
                <h3>{item.original_filename}</h3>
                <p className="error-text">{item.error}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="tool-panel smart-import-dropzone">
        <div className="field">
          <label htmlFor="smart_files">Fichiers Uber ou preuves</label>
          <input
            id="smart_files"
            type="file"
            multiple
            accept={acceptedTypes}
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
        </div>
        {files.length > 0 ? (
          <div className="chip-list">
            {files.map((file) => (
              <span key={`${file.name}-${file.size}`} className="chip">
                {file.name}
              </span>
            ))}
          </div>
        ) : (
          <PremiumEmptyState
            title="Aucun fichier selectionne"
            description="CSV, XLSX, PDF, images et ZIP sont acceptes. Le nom du fichier n'est pas obligatoire."
          />
        )}
        <div className="actions">
          <button type="button" className="button" onClick={handlePreview} disabled={loading || files.length === 0}>
            {loading ? "TENNET travaille" : "Lancer TENNET"}
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setFiles([]);
              setPreview(null);
              setDecisions({});
              setConfirmResult(null);
              setSuccess(null);
            }}
          >
            Reinitialiser
          </button>
        </div>
      </section>

      {preview && !confirmResult ? (
        <section className="tool-panel">
          <div className="section-heading">
            <div>
              <h2>Ce que TENNET a compris</h2>
              <p className="muted">Import #{preview.batch_preview_id}. TENNET a deja lance le traitement recommande.</p>
            </div>
            <button type="button" className="button" onClick={handleConfirm} disabled={confirming || preview.status === "confirmed"}>
              {confirming ? "Creation" : "Relancer avec corrections"}
            </button>
          </div>
          <div className="premium-card-grid">
            {preview.files.map((file) => (
              <article key={file.id} className="premium-card">
                <SmartImportPreviewCard file={file} />
                {isExactDuplicate(file) ? <div className="success-box">Fichier doublon ignore automatiquement.</div> : null}
                <details className="simple-details simple-details--compact">
                  <summary>Corriger si besoin</summary>
                  <div className="detail-grid detail-grid--compact">
                    <label className="field">
                      <span>Destination</span>
                      <select
                        value={decisions[file.id]?.action ?? file.recommended_action}
                        onChange={(event) =>
                          updateDecision(file.id, { action: event.target.value as SmartImportRecommendedAction })
                        }
                        disabled={isExactDuplicate(file)}
                      >
                        <option value="import_uber_reporting">Import Uber</option>
                        <option value="import_evidence_bulk">Import preuves</option>
                        <option value="manual_review">A verifier</option>
                        <option value="ignore">Ignorer</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Type Uber</span>
                      <select
                        value={decisions[file.id]?.report_type ?? file.detected_report_type ?? "combined_report"}
                        onChange={(event) => updateDecision(file.id, { report_type: event.target.value as UberReportingReportType })}
                        disabled={isExactDuplicate(file) || (decisions[file.id]?.action ?? file.recommended_action) !== "import_uber_reporting"}
                      >
                        <option value="combined_report">Rapport Uber detecte</option>
                        <option value="orders_report">Commandes Uber</option>
                        <option value="payments_report">Paiements Uber</option>
                        <option value="adjustments_report">Ajustements Uber</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Restaurant</span>
                      <select
                        value={decisions[file.id]?.restaurant_id ?? ""}
                        onChange={(event) =>
                          updateDecision(file.id, { restaurant_id: event.target.value ? Number(event.target.value) : null })
                        }
                        disabled={isExactDuplicate(file)}
                      >
                        <option value="">TENNET propose</option>
                        {restaurants.map((restaurant) => (
                          <option key={restaurant.id} value={restaurant.id}>
                            {restaurant.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </details>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <MobileActionBar>
        <button type="button" className="button" onClick={handlePreview} disabled={loading || files.length === 0}>
          Lancer
        </button>
        {preview && !confirmResult ? (
          <button type="button" className="secondary-button" onClick={handleConfirm} disabled={confirming || preview.status === "confirmed"}>
            Corriger
          </button>
        ) : null}
      </MobileActionBar>
    </section>
  );

  function updateDecision(fileId: number, patch: Partial<SmartImportFileDecision>) {
    setDecisions((current) => ({
      ...current,
      [fileId]: {
        ...(current[fileId] ?? {}),
        ...patch,
        file_id: fileId,
      },
    }));
  }
}

function labelForDestination(file: SmartImportConfirmResponse["routed_files"][number]): string {
  if (file.destination_type === "uber_reporting_batch") {
    return `Rapport Uber applique (${file.processing_status ?? "traite"}).`;
  }
  if (file.destination_type === "evidence_import_batch") {
    return `Preuves rangees et analysees (${file.processing_status ?? "stocke"}).`;
  }
  return "Workflow cree.";
}

function hasDestination(result: SmartImportConfirmResponse, destinationType: string): boolean {
  return result.routed_files.some((file) => file.destination_type === destinationType);
}

function isExactDuplicate(file: { status?: string; destination_type?: string | null }): boolean {
  return file.status === "ignored" && file.destination_type === "duplicate_ignored";
}
