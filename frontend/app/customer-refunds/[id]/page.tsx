"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type CustomerRefundDisputeDetail,
  type EvidenceType,
} from "@/lib/api";

export default function CustomerRefundDetailPage() {
  const params = useParams<{ id: string }>();
  const disputeId = Number(params.id);
  const [detail, setDetail] = useState<CustomerRefundDisputeDetail | null>(null);
  const [selectedEvidenceType, setSelectedEvidenceType] = useState<EvidenceType>("receipt");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [ignoreReason, setIgnoreReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    const data = await api.getCustomerRefundDispute(disputeId);
    setDetail(data);
    const pendingRequirement = data.evidence_requirements.find((requirement) => requirement.status === "pending");
    setSelectedEvidenceType(pendingRequirement?.required_evidence_type ?? data.evidence_requirements[0]?.required_evidence_type ?? "receipt");
  }, [disputeId]);

  useEffect(() => {
    if (!Number.isFinite(disputeId)) {
      setError(new Error("Deduction invalide"));
      setLoading(false);
      return;
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [disputeId, loadData]);

  const evidenceOptions = useMemo(() => {
    const requiredTypes = detail?.evidence_requirements.map((requirement) => requirement.required_evidence_type) ?? [];
    return Array.from(new Set<EvidenceType>(["receipt", ...requiredTypes]));
  }, [detail]);

  async function runAction(action: string, callback: () => Promise<unknown>) {
    setWorking(action);
    setActionError(null);
    try {
      await callback();
      await loadData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setWorking(null);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail?.claim_order || !selectedFile) {
      setActionError(new Error("Creez d'abord un dossier TENNET puis selectionnez un fichier."));
      return;
    }
    await runAction("upload", async () => {
      await api.uploadEvidence(detail.claim_order!.id, selectedEvidenceType, selectedFile);
      await api.recalculateCustomerRefundEvidence(disputeId);
      setSelectedFile(null);
      setFileInputKey((current) => current + 1);
    });
  }

  async function handleIgnore() {
    const reason = ignoreReason.trim();
    if (!reason) {
      setActionError(new Error("Renseignez une raison d'ignorance."));
      return;
    }
    await runAction("ignore", () => api.ignoreCustomerRefundDispute(disputeId, { reason }));
  }

  if (loading) {
    return <LoadingState label="Chargement deduction Uber" />;
  }

  if (!detail) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Deduction introuvable" />
      </section>
    );
  }

  const { dispute } = detail;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Deduction Uber</p>
          <h1>{dispute.display_id || dispute.uber_order_id || `Dispute #${dispute.id}`}</h1>
          <p>Chaque contestation reste basee sur des preuves et une action humaine.</p>
        </div>
        <div className="actions">
          <Link href="/customer-refunds" className="secondary-button">
            Retour deductions
          </Link>
          {detail.claim_order ? (
            <Link href={`/orders/${detail.claim_order.id}`} className="secondary-button">
              Ouvrir dossier
            </Link>
          ) : null}
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <div className="stats-grid">
        <StatCard label="Montant deduit" value={formatCurrency(dispute.customer_refund_amount, dispute.currency)} />
        <StatCard label="Montant commande" value={formatCurrency(dispute.order_amount, dispute.currency)} />
        <StatCard label="Statut" value={dispute.status} />
        <StatCard label="Preuves" value={dispute.evidence_status} />
      </div>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Resume</h2>
          <div className="actions">
            <StatusBadge status={dispute.status} />
            <StatusBadge status={dispute.evidence_status} />
          </div>
        </div>
        <div className="detail-grid">
          <DetailItem label="Restaurant" value={detail.restaurant_name} />
          <DetailItem label="Type" value={dispute.dispute_type} />
          <DetailItem label="Raison" value={dispute.reason} />
          <DetailItem label="Commande Uber" value={dispute.uber_order_id ?? "-"} />
          <DetailItem label="Display ID" value={dispute.display_id ?? "-"} />
          <DetailItem label="Deduit le" value={formatDate(dispute.deducted_at)} />
          <DetailItem label="Transaction" value={dispute.financial_transaction_id ? `#${dispute.financial_transaction_id}` : "-"} />
          <DetailItem label="Brouillon interne" value={dispute.dispute_email_draft_id ? `#${dispute.dispute_email_draft_id}` : "-"} />
          <DetailItem label="Brouillon Gmail" value={dispute.provider_draft_id ? `#${dispute.provider_draft_id}` : "-"} />
        </div>
        {dispute.notes ? <p className="muted">{dispute.notes}</p> : null}
      </section>

      <section className="grid-two">
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Preuves requises</h2>
            <button
              type="button"
              className="secondary-button"
              disabled={working === "recalculate"}
              onClick={() => runAction("recalculate", () => api.recalculateCustomerRefundEvidence(disputeId))}
            >
              Recalculer
            </button>
          </div>
          {detail.evidence_requirements.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Statut</th>
                    <th>Fichier</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.evidence_requirements.map((requirement) => (
                    <tr key={requirement.id}>
                      <td>{requirement.required_evidence_type}</td>
                      <td>
                        <StatusBadge status={requirement.status} />
                      </td>
                      <td>{requirement.evidence_file_id ? `#${requirement.evidence_file_id}` : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Aucune preuve obligatoire" />
          )}
        </section>

        <form className="tool-panel" onSubmit={handleUpload}>
          <div className="section-heading">
            <h2>Upload preuve</h2>
            <span className="muted">{detail.claim_order ? "Fichier ajoute au dossier lie." : "Creez le dossier avant upload."}</span>
          </div>
          <div className="field">
            <label htmlFor="evidence_type">Type preuve</label>
            <select
              id="evidence_type"
              value={selectedEvidenceType}
              onChange={(event) => setSelectedEvidenceType(event.target.value as EvidenceType)}
              disabled={!detail.claim_order}
            >
              {evidenceOptions.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="evidence_file">Fichier</label>
            <input
              key={fileInputKey}
              id="evidence_file"
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
              disabled={!detail.claim_order}
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </div>
          <button type="submit" className="button" disabled={!detail.claim_order || working === "upload"}>
            Ajouter la preuve
          </button>
        </form>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Actions controlees</h2>
          <span className="muted">Aucun email n'est envoye automatiquement.</span>
        </div>
        <div className="actions">
          <button
            type="button"
            className="button"
            disabled={Boolean(dispute.claim_order_id) || working === "claim"}
            onClick={() => runAction("claim", () => api.createClaimOrderFromCustomerRefund(disputeId))}
          >
            Creer dossier TENNET
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={working === "draft" || dispute.evidence_status === "missing"}
            onClick={() => runAction("draft", () => api.createCustomerRefundDraft(disputeId))}
          >
            Creer brouillon interne
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={working === "gmail" || !dispute.dispute_email_draft_id}
            onClick={() => runAction("gmail", () => api.createCustomerRefundGmailDraft(disputeId))}
          >
            Creer brouillon Gmail
          </button>
        </div>
      </section>

      <section className="grid-two">
        <section className="tool-panel">
          <h2>Taches preuves</h2>
          {detail.evidence_tasks.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Preuve</th>
                    <th>Statut</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.evidence_tasks.map((task) => (
                    <tr key={task.id}>
                      <td>{task.required_evidence_type}</td>
                      <td>
                        <StatusBadge status={task.status} />
                      </td>
                      <td>
                        <Link href={`/evidence-tasks/${task.id}`} className="secondary-button">
                          Ouvrir
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Aucune tache preuve liee" />
          )}
        </section>

        <section className="tool-panel">
          <h2>Ignorer</h2>
          <div className="inline-form">
            <input
              aria-label="Raison ignorance deduction"
              placeholder="Raison"
              value={ignoreReason}
              onChange={(event) => setIgnoreReason(event.target.value)}
            />
            <button type="button" className="danger-button" disabled={working === "ignore" || dispute.status === "ignored"} onClick={handleIgnore}>
              Ignorer
            </button>
          </div>
          {dispute.ignore_reason ? <p className="muted">Raison: {dispute.ignore_reason}</p> : null}
        </section>
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
