"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  emptyToNull,
  formatCurrency,
  type ClaimOrder,
  type ClaimValidationResponse,
  type EmailDraft,
  type EvidenceFile,
  type EvidenceType,
  type Restaurant,
} from "@/lib/api";

type EvidenceForm = {
  evidence_type: EvidenceType;
  original_filename: string;
  storage_path: string;
  mime_type: string;
  file_size: string;
};

const initialEvidenceForm: EvidenceForm = {
  evidence_type: "cancellation_proof",
  original_filename: "",
  storage_path: "",
  mime_type: "",
  file_size: "",
};

const evidenceTypes: EvidenceType[] = [
  "receipt",
  "cancellation_proof",
  "preparation_proof",
  "waste_photo",
  "uber_screenshot",
  "other",
];

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const orderId = Number(params.id);
  const [order, setOrder] = useState<ClaimOrder | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [evidence, setEvidence] = useState<EvidenceFile[]>([]);
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [validation, setValidation] = useState<ClaimValidationResponse | null>(null);
  const [generatedDraft, setGeneratedDraft] = useState<EmailDraft | null>(null);
  const [evidenceForm, setEvidenceForm] = useState<EvidenceForm>(initialEvidenceForm);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submittingEvidence, setSubmittingEvidence] = useState(false);
  const [validating, setValidating] = useState(false);
  const [generatingDraft, setGeneratingDraft] = useState(false);

  const loadOrderData = useCallback(async () => {
    const [orderData, restaurantsData, evidenceData, draftsData] = await Promise.all([
      api.getOrder(orderId),
      api.getRestaurants(),
      api.getEvidence(orderId),
      api.getOrderDrafts(orderId),
    ]);
    setOrder(orderData);
    setRestaurants(restaurantsData);
    setEvidence(evidenceData);
    setDrafts(draftsData);
  }, [orderId]);

  useEffect(() => {
    if (!Number.isFinite(orderId)) {
      setError(new Error("Commande invalide"));
      setLoading(false);
      return;
    }

    loadOrderData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadOrderData, orderId]);

  const restaurant = useMemo(
    () => restaurants.find((item) => item.id === order?.restaurant_id) ?? null,
    [order?.restaurant_id, restaurants],
  );

  async function handleAddEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingEvidence(true);
    setActionError(null);

    try {
      await api.createEvidence(orderId, {
        evidence_type: evidenceForm.evidence_type,
        original_filename: evidenceForm.original_filename.trim(),
        storage_path: evidenceForm.storage_path.trim(),
        mime_type: emptyToNull(evidenceForm.mime_type),
        file_size: evidenceForm.file_size ? Number(evidenceForm.file_size) : null,
      });
      setEvidenceForm(initialEvidenceForm);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmittingEvidence(false);
    }
  }

  async function handleValidate() {
    setValidating(true);
    setActionError(null);
    setValidation(null);

    try {
      const result = await api.validateOrder(orderId);
      setValidation(result);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setValidating(false);
    }
  }

  async function handleGenerateInitialDraft() {
    setGeneratingDraft(true);
    setActionError(null);
    setGeneratedDraft(null);

    try {
      const draft = await api.createOrderDraft(orderId, "initial_claim");
      setGeneratedDraft(draft);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setGeneratingDraft(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement de la commande" />;
  }

  if (!order) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Commande introuvable" />
      </section>
    );
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Commande</p>
          <h1>{order.uber_order_number}</h1>
        </div>
        <div className="actions">
          <Link href="/orders" className="secondary-button">
            Retour commandes
          </Link>
          <button type="button" className="secondary-button" onClick={handleValidate} disabled={validating}>
            {validating ? "Validation" : "Valider dossier"}
          </button>
          <button type="button" className="button" onClick={handleGenerateInitialDraft} disabled={generatingDraft}>
            {generatingDraft ? "Generation" : "Generer brouillon initial"}
          </button>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Informations commande</h2>
          <StatusBadge status={order.status} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Restaurant" value={restaurant?.name ?? `#${order.restaurant_id}`} />
          <DetailItem label="Reference interne" value={order.internal_reference ?? "-"} />
          <DetailItem label="Client" value={order.customer_name ?? "-"} />
          <DetailItem label="Date" value={order.order_date ?? "-"} />
          <DetailItem label="Montant" value={formatCurrency(order.order_amount, order.currency)} />
          <DetailItem label="Devise" value={order.currency} />
          <DetailItem label="Retry count" value={String(order.retry_count)} />
          <DetailItem label="Resultat" value={order.result ?? "-"} />
          <DetailItem label="Type de perte" value={order.loss_type ?? "-"} />
        </div>
      </section>

      {validation ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Validation</h2>
            <StatusBadge status={validation.is_complete ? "ready_to_send" : "missing_evidence"} />
          </div>
          <div className="detail-grid">
            <DetailItem label="Ancien statut" value={validation.previous_status ?? "-"} />
            <DetailItem label="Nouveau statut" value={validation.new_status ?? "-"} />
            <DetailItem label="Complete" value={validation.is_complete ? "oui" : "non"} />
          </div>
          <ResultList title="missing_items" values={validation.missing_items} />
          <ResultList title="blocking_reasons" values={validation.blocking_reasons} />
        </section>
      ) : null}

      <section className="grid-two">
        <div className="tool-panel">
          <h2>Preuves</h2>
          {evidence.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Fichier</th>
                    <th>Chemin</th>
                    <th>MIME</th>
                    <th>Taille</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.map((item) => (
                    <tr key={item.id}>
                      <td>{item.evidence_type}</td>
                      <td>{item.original_filename}</td>
                      <td>{item.storage_path}</td>
                      <td>{item.mime_type ?? "-"}</td>
                      <td>{item.file_size ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Aucune preuve" />
          )}
        </div>

        <form className="tool-panel" onSubmit={handleAddEvidence}>
          <h2>Ajouter preuve</h2>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="evidence_type">Type</label>
              <select
                id="evidence_type"
                value={evidenceForm.evidence_type}
                onChange={(event) =>
                  setEvidenceForm((current) => ({
                    ...current,
                    evidence_type: event.target.value as EvidenceType,
                  }))
                }
              >
                {evidenceTypes.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="original_filename">Nom fichier</label>
              <input
                id="original_filename"
                required
                value={evidenceForm.original_filename}
                onChange={(event) =>
                  setEvidenceForm((current) => ({
                    ...current,
                    original_filename: event.target.value,
                  }))
                }
              />
            </div>
            <div className="field field--full">
              <label htmlFor="storage_path">Chemin stockage</label>
              <input
                id="storage_path"
                required
                value={evidenceForm.storage_path}
                onChange={(event) => setEvidenceForm((current) => ({ ...current, storage_path: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="mime_type">MIME</label>
              <input
                id="mime_type"
                value={evidenceForm.mime_type}
                onChange={(event) => setEvidenceForm((current) => ({ ...current, mime_type: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="file_size">Taille</label>
              <input
                id="file_size"
                inputMode="numeric"
                value={evidenceForm.file_size}
                onChange={(event) => setEvidenceForm((current) => ({ ...current, file_size: event.target.value }))}
              />
            </div>
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={submittingEvidence}>
              {submittingEvidence ? "Ajout" : "Ajouter preuve"}
            </button>
          </div>
        </form>
      </section>

      <section className="tool-panel">
        <h2>Brouillons</h2>
        {generatedDraft ? (
          <div className="success-box">
            <strong>Brouillon genere</strong>
            <span>{generatedDraft.subject}</span>
          </div>
        ) : null}
        {drafts.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Sujet</th>
                  <th>Statut</th>
                  <th>Corps</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((draft) => (
                  <tr key={draft.id}>
                    <td>{draft.draft_type}</td>
                    <td>{draft.subject}</td>
                    <td>
                      <StatusBadge status={draft.status} />
                    </td>
                    <td>
                      <pre className="draft-body">{draft.body}</pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Aucun brouillon" />
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

function ResultList({ title, values }: { title: string; values: string[] }) {
  if (values.length === 0) {
    return (
      <div>
        <h3>{title}</h3>
        <p className="muted">-</p>
      </div>
    );
  }

  return (
    <div>
      <h3>{title}</h3>
      <ul className="result-list">
        {values.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
    </div>
  );
}
