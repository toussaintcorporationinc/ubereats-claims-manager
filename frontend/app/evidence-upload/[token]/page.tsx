"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type EvidenceTaskUploadResponse,
  type PublicEvidenceUploadLink,
} from "@/lib/api";

export default function PublicEvidenceUploadPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [link, setLink] = useState<PublicEvidenceUploadLink | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<EvidenceTaskUploadResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const loadLink = useCallback(async () => {
    setLink(await api.getPublicEvidenceUploadLink(token));
  }, [token]);

  useEffect(() => {
    loadLink()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadLink]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setActionError(new Error("Selectionnez un fichier de preuve."));
      return;
    }
    setSubmitting(true);
    setActionError(null);
    setUploadResult(null);

    try {
      const result = await api.uploadPublicEvidenceLink(token, selectedFile);
      setUploadResult(result);
      await loadLink();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Verification du lien" />;
  }

  return (
    <section className="auth-panel">
        <div className="heading-copy">
          <p className="eyebrow">TENNET</p>
          <h1>Ajouter une preuve</h1>
        </div>

        <ApiError error={error} />
        <ApiError error={actionError} />

        {link ? (
          <form className="tool-panel" onSubmit={handleSubmit}>
            <div className="section-heading">
              <h2>{link.title}</h2>
              <StatusBadge status={link.priority} />
            </div>
            <div className="detail-grid">
              <DetailItem label="Restaurant" value={link.restaurant_name} />
              <DetailItem label="Commande" value={link.uber_order_number} />
              <DetailItem label="Preuve" value={link.required_evidence_type} />
              <DetailItem label="Expiration" value={formatDate(link.expires_at)} />
            </div>
            {link.description ? <p className="muted">{link.description}</p> : null}
            <p className="muted">
              Ce lien sert uniquement a joindre la preuve demandee. Aucun email n'est envoye automatiquement.
            </p>
            <div className="field">
              <label htmlFor="public_evidence_file">Fichier</label>
              <input
                id="public_evidence_file"
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
                required
                disabled={Boolean(uploadResult)}
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <button type="submit" className="button" disabled={submitting || Boolean(uploadResult)}>
              {submitting ? "Ajout" : uploadResult ? "Preuve ajoutee" : "Envoyer la preuve"}
            </button>
            {uploadResult ? (
              <div className="success-box">
                <strong>Preuve recue</strong>
                <span>{uploadResult.evidence_file.original_filename}</span>
                <span>Statut dossier: {uploadResult.validation.new_status ?? "-"}</span>
              </div>
            ) : null}
          </form>
        ) : null}
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
