"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type ClaimOrder,
  type EvidenceRequestTask,
  type EvidenceTaskUploadResponse,
  type EvidenceUploadLinkCreateResponse,
  type Restaurant,
} from "@/lib/api";

export default function EvidenceTaskDetailPage() {
  const params = useParams<{ id: string }>();
  const taskId = Number(params.id);
  const [task, setTask] = useState<EvidenceRequestTask | null>(null);
  const [order, setOrder] = useState<ClaimOrder | null>(null);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [skipReason, setSkipReason] = useState("");
  const [uploadResult, setUploadResult] = useState<EvidenceTaskUploadResponse | null>(null);
  const [linkResult, setLinkResult] = useState<EvidenceUploadLinkCreateResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [creatingLink, setCreatingLink] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [completing, setCompleting] = useState(false);

  const loadData = useCallback(async () => {
    const taskData = await api.getEvidenceTask(taskId);
    const [orderData, restaurantsData] = await Promise.all([api.getOrder(taskData.order_id), api.getRestaurants()]);
    setTask(taskData);
    setOrder(orderData);
    setRestaurant(restaurantsData.find((item) => item.id === orderData.restaurant_id) ?? null);
  }, [taskId]);

  useEffect(() => {
    if (!Number.isFinite(taskId)) {
      setError(new Error("Tache invalide"));
      setLoading(false);
      return;
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData, taskId]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) {
      setActionError(new Error("Selectionnez un fichier de preuve."));
      return;
    }
    setSubmitting(true);
    setActionError(null);
    setUploadResult(null);

    try {
      const result = await api.uploadEvidenceTask(taskId, selectedFile);
      setUploadResult(result);
      setSelectedFile(null);
      setFileInputKey((current) => current + 1);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCreateLink() {
    setCreatingLink(true);
    setActionError(null);
    setLinkResult(null);

    try {
      setLinkResult(await api.createEvidenceUploadLink(taskId));
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setCreatingLink(false);
    }
  }

  async function handleSkip() {
    const reason = skipReason.trim();
    if (!reason) {
      setActionError(new Error("Renseignez une raison pour ignorer la demande."));
      return;
    }
    setSkipping(true);
    setActionError(null);

    try {
      await api.skipEvidenceTask(taskId, { skip_reason: reason });
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSkipping(false);
    }
  }

  async function handleComplete() {
    setCompleting(true);
    setActionError(null);

    try {
      await api.completeEvidenceTask(taskId);
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setCompleting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement de la demande de preuve" />;
  }

  if (!task || !order) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Demande de preuve introuvable" />
      </section>
    );
  }

  const isActive = task.status === "pending" || task.status === "uploaded";

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuve a fournir</p>
          <h1>{task.title}</h1>
        </div>
        <div className="actions">
          <Link href="/evidence-tasks" className="secondary-button">
            Retour preuves
          </Link>
          <Link href={`/orders/${order.id}`} className="secondary-button">
            Ouvrir commande
          </Link>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Contexte</h2>
          <div className="actions">
            <StatusBadge status={task.priority} />
            <StatusBadge status={task.status} />
          </div>
        </div>
        <div className="detail-grid">
          <DetailItem label="Restaurant" value={restaurant?.name ?? `#${order.restaurant_id}`} />
          <DetailItem label="Commande Uber" value={order.uber_order_number} />
          <DetailItem label="Statut dossier" value={order.status} />
          <DetailItem label="Montant" value={formatCurrency(order.order_amount, order.currency)} />
          <DetailItem label="Type preuve" value={task.required_evidence_type} />
          <DetailItem label="Echeance" value={formatDate(task.due_at)} />
          <DetailItem label="Raison" value={task.reason} />
          <DetailItem label="Creee le" value={formatDate(task.created_at)} />
        </div>
        {task.description ? <p className="muted">{task.description}</p> : null}
      </section>

      {uploadResult ? (
        <section className="tool-panel">
          <div className="success-box">
            <strong>Preuve ajoutee</strong>
            <span>{uploadResult.evidence_file.original_filename}</span>
            <span>Statut validation: {uploadResult.validation.new_status ?? "-"}</span>
          </div>
        </section>
      ) : null}

      <section className="grid-two">
        <form className="tool-panel" onSubmit={handleUpload}>
          <div className="section-heading">
            <h2>Upload direct</h2>
            <StatusBadge status={task.required_evidence_type} />
          </div>
          <div className="field">
            <label htmlFor="task_file">Fichier</label>
            <input
              key={fileInputKey}
              id="task_file"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
              disabled={!isActive}
              required
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <button type="submit" className="button" disabled={!isActive || submitting}>
            {submitting ? "Ajout" : "Ajouter la preuve"}
          </button>
        </form>

        <section className="tool-panel">
          <div className="section-heading">
            <h2>Lien mobile</h2>
            <span className="muted">Token affiche une seule fois. Aucun mot de passe requis.</span>
          </div>
          <button type="button" className="button" onClick={handleCreateLink} disabled={!isActive || creatingLink}>
            {creatingLink ? "Creation" : "Creer lien mobile"}
          </button>
          {linkResult ? (
            <div className="success-box">
              <strong>Lien cree</strong>
              <input readOnly value={linkResult.upload_url} aria-label="Lien upload mobile" />
              <span>Expiration: {formatDate(linkResult.expires_at)}</span>
            </div>
          ) : null}
        </section>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Traitement manuel</h2>
          <span className="muted">Toute decision reste tracee.</span>
        </div>
        <div className="inline-form">
          <input
            aria-label="Raison skip preuve"
            placeholder="Raison si preuve impossible"
            value={skipReason}
            onChange={(event) => setSkipReason(event.target.value)}
          />
          <button type="button" className="danger-button" onClick={handleSkip} disabled={task.status === "completed" || skipping}>
            {skipping ? "Ignorer" : "Ignorer"}
          </button>
          <button type="button" className="secondary-button" onClick={handleComplete} disabled={!isActive || completing}>
            {completing ? "Terminer" : "Marquer complete"}
          </button>
        </div>
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
