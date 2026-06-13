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
      setDecisions(
        Object.fromEntries(
          result.files.map((file) => [
            file.id,
            {
              file_id: file.id,
              action: file.recommended_action,
              report_type: file.detected_report_type ?? "combined_report",
              restaurant_id: null,
            },
          ]),
        ),
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
          <p>TENNET detecte le type par contenu et propose l'action la plus simple.</p>
        </div>
      </div>

      <ApiError error={error} />
      {success ? <div className="success-box">{success}</div> : null}

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
            {loading ? "Analyse" : "Analyser"}
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

      {preview ? (
        <section className="tool-panel">
          <div className="section-heading">
            <div>
              <h2>Preview</h2>
              <p className="muted">Batch #{preview.batch_preview_id} - {preview.status}</p>
            </div>
            <button type="button" className="button" onClick={handleConfirm} disabled={confirming || preview.status === "confirmed"}>
              {confirming ? "Confirmation" : "Confirmer"}
            </button>
          </div>
          <div className="premium-card-grid">
            {preview.files.map((file) => (
              <article key={file.id} className="premium-card">
                <SmartImportPreviewCard file={file} />
                {isExactDuplicate(file) ? <div className="success-box">Fichier doublon ignore automatiquement.</div> : null}
                <div className="detail-grid detail-grid--compact">
                  <label className="field">
                    <span>Action</span>
                    <select
                      value={decisions[file.id]?.action ?? file.recommended_action}
                      onChange={(event) =>
                        updateDecision(file.id, { action: event.target.value as SmartImportRecommendedAction })
                      }
                      disabled={isExactDuplicate(file)}
                    >
                      <option value="import_uber_reporting">Creer import Uber</option>
                      <option value="import_evidence_bulk">Creer import preuves</option>
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
                      <option value="">Non force</option>
                      {restaurants.map((restaurant) => (
                        <option key={restaurant.id} value={restaurant.id}>
                          {restaurant.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {confirmResult ? (
        <section className="tool-panel">
          <div className="section-heading">
            <div>
              <h2>Resultat</h2>
              <p className="muted">TENNET a cree les workflows sans confirmer les lignes financieres automatiquement.</p>
            </div>
          </div>
          <div className="premium-card-grid">
            {confirmResult.routed_files.map((file) => (
              <article key={`${file.file_id}-${file.destination_type}`} className="premium-card">
                <h3>{file.original_filename}</h3>
                <p className="muted">{labelForDestination(file.destination_type)}</p>
                {file.destination_url ? (
                  <Link className="button" href={file.destination_url}>
                    Ouvrir
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
                  {file.destination_type === "duplicate_ignored" ? "Doublon exact supprime. TENNET garde le fichier canonique." : "Fichier ignore."}
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

      <MobileActionBar>
        <button type="button" className="button" onClick={handlePreview} disabled={loading || files.length === 0}>
          Analyser
        </button>
        {preview ? (
          <button type="button" className="secondary-button" onClick={handleConfirm} disabled={confirming || preview.status === "confirmed"}>
            Confirmer
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

function labelForDestination(destinationType: string | null): string {
  const labels: Record<string, string> = {
    uber_reporting_batch: "Import Uber cree. Ouvrez le batch pour confirmer les lignes.",
    evidence_import_batch: "Import de preuves cree. Ouvrez le batch pour analyser et attacher.",
  };
  return destinationType ? (labels[destinationType] ?? destinationType) : "Workflow cree";
}

function isExactDuplicate(file: { status?: string; destination_type?: string | null }): boolean {
  return file.status === "ignored" && file.destination_type === "duplicate_ignored";
}
