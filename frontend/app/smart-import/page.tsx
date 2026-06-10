"use client";

import { useState } from "react";
import ApiError from "@/components/ApiError";
import MobileActionBar from "@/components/MobileActionBar";
import PremiumEmptyState from "@/components/PremiumEmptyState";
import SmartImportPreviewCard from "@/components/SmartImportPreviewCard";
import { api, type SmartImportPreviewResponse } from "@/lib/api";

const acceptedTypes = ".csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.zip,image/*,application/pdf";

export default function SmartImportPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<SmartImportPreviewResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);

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
      const result = await api.confirmSmartImport(preview.batch_preview_id);
      setSuccess(`Preview confirmee : ${result.recommended_actions.join(", ")}`);
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
              <SmartImportPreviewCard key={file.id} file={file} />
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
}
