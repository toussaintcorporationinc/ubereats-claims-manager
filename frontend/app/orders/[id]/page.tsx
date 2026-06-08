"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  formatCurrency,
  type ClaimOrder,
  type ClaimValidationResponse,
  type EmailDraft,
  type EmailProviderDraft,
  type EvidenceFile,
  type EvidenceType,
  type GmailConnectionStatus,
  type GmailDraftSendResponse,
  type OrderEmailMessagesResponse,
  type Restaurant,
} from "@/lib/api";

const defaultRecipient = "merchants@uber.com";

type EvidenceForm = {
  evidence_type: EvidenceType;
};

type GmailDraftForm = {
  to_email: string;
  include_evidence: boolean;
};

const initialEvidenceForm: EvidenceForm = {
  evidence_type: "cancellation_proof",
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
  const { user } = useAuth();
  const [order, setOrder] = useState<ClaimOrder | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [evidence, setEvidence] = useState<EvidenceFile[]>([]);
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [emailMessages, setEmailMessages] = useState<OrderEmailMessagesResponse | null>(null);
  const [gmailStatus, setGmailStatus] = useState<GmailConnectionStatus | null>(null);
  const [validation, setValidation] = useState<ClaimValidationResponse | null>(null);
  const [generatedDraft, setGeneratedDraft] = useState<EmailDraft | null>(null);
  const [gmailDraftResult, setGmailDraftResult] = useState<EmailProviderDraft | null>(null);
  const [gmailSendResult, setGmailSendResult] = useState<GmailDraftSendResponse | null>(null);
  const [evidenceForm, setEvidenceForm] = useState<EvidenceForm>(initialEvidenceForm);
  const [gmailForms, setGmailForms] = useState<Record<number, GmailDraftForm>>({});
  const [sendConfirmations, setSendConfirmations] = useState<Record<number, boolean>>({});
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submittingEvidence, setSubmittingEvidence] = useState(false);
  const [downloadingEvidenceId, setDownloadingEvidenceId] = useState<number | null>(null);
  const [validating, setValidating] = useState(false);
  const [generatingDraft, setGeneratingDraft] = useState(false);
  const [submittingGmailDraftId, setSubmittingGmailDraftId] = useState<number | null>(null);
  const [sendingProviderDraftId, setSendingProviderDraftId] = useState<string | null>(null);

  const loadOrderData = useCallback(async () => {
    const [orderData, restaurantsData, evidenceData, draftsData, emailMessagesData] = await Promise.all([
      api.getOrder(orderId),
      api.getRestaurants(),
      api.getEvidence(orderId),
      api.getOrderDrafts(orderId),
      api.getOrderEmailMessages(orderId),
    ]);
    setOrder(orderData);
    setRestaurants(restaurantsData);
    setEvidence(evidenceData);
    setDrafts(draftsData);
    setEmailMessages(emailMessagesData);
  }, [orderId]);

  useEffect(() => {
    if (!Number.isFinite(orderId)) {
      setError(new Error("Commande invalide"));
      setLoading(false);
      return;
    }

    async function loadData() {
      await loadOrderData();
      if (user?.role === "owner" || user?.role === "manager") {
        setGmailStatus(await api.getGmailStatus());
      }
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadOrderData, orderId, user?.role]);

  const restaurant = useMemo(
    () => restaurants.find((item) => item.id === order?.restaurant_id) ?? null,
    [order?.restaurant_id, restaurants],
  );
  const canValidateOrDraft = user?.role === "owner" || user?.role === "manager";

  async function handleAddEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingEvidence(true);
    setActionError(null);

    try {
      if (!selectedFile) {
        throw new Error("Selectionnez un fichier de preuve.");
      }
      await api.uploadEvidence(orderId, evidenceForm.evidence_type, selectedFile);
      setEvidenceForm(initialEvidenceForm);
      setSelectedFile(null);
      setFileInputKey((current) => current + 1);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmittingEvidence(false);
    }
  }

  async function handleDownloadEvidence(item: EvidenceFile) {
    setDownloadingEvidenceId(item.id);
    setActionError(null);

    try {
      const blob = await api.downloadEvidence(item.id);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = item.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloadingEvidenceId(null);
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

  function getGmailForm(draftId: number): GmailDraftForm {
    return gmailForms[draftId] ?? { to_email: defaultRecipient, include_evidence: true };
  }

  function updateGmailForm(draftId: number, patch: Partial<GmailDraftForm>) {
    setGmailForms((current) => ({
      ...current,
      [draftId]: {
        ...getGmailForm(draftId),
        ...patch,
      },
    }));
  }

  async function handleCreateGmailDraft(draftId: number) {
    setSubmittingGmailDraftId(draftId);
    setActionError(null);
    setGmailDraftResult(null);
    setGmailSendResult(null);

    try {
      const form = getGmailForm(draftId);
      const result = await api.createGmailDraft(draftId, {
        to_email: form.to_email,
        include_evidence: form.include_evidence,
      });
      setGmailDraftResult(result);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmittingGmailDraftId(null);
    }
  }

  async function handleSendGmailDraft(draft: EmailDraft) {
    if (!draft.provider_draft_id) {
      return;
    }
    setSendingProviderDraftId(draft.provider_draft_id);
    setActionError(null);
    setGmailSendResult(null);

    try {
      const result = await api.sendGmailProviderDraft(draft.provider_draft_id, { confirm_send: true });
      setGmailSendResult(result);
      await loadOrderData();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSendingProviderDraftId(null);
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
          {canValidateOrDraft ? (
            <>
              <button type="button" className="secondary-button" onClick={handleValidate} disabled={validating}>
                {validating ? "Validation" : "Valider dossier"}
              </button>
              <button type="button" className="button" onClick={handleGenerateInitialDraft} disabled={generatingDraft}>
                {generatingDraft ? "Generation" : "Generer brouillon initial"}
              </button>
            </>
          ) : null}
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
                    <th>MIME</th>
                    <th>Taille</th>
                    <th>Checksum</th>
                    <th>Ajout</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {evidence.map((item) => (
                    <tr key={item.id}>
                      <td>{item.evidence_type}</td>
                      <td>{item.original_filename}</td>
                      <td>{item.mime_type ?? "-"}</td>
                      <td>{formatFileSize(item.file_size)}</td>
                      <td>{item.checksum_sha256 ? item.checksum_sha256.slice(0, 12) : "-"}</td>
                      <td>{formatDate(item.uploaded_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => handleDownloadEvidence(item)}
                          disabled={downloadingEvidenceId === item.id}
                        >
                          {downloadingEvidenceId === item.id ? "Ouverture" : "Telecharger"}
                        </button>
                      </td>
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
            <div className="field field--full">
              <label htmlFor="evidence_file">Fichier</label>
              <input
                key={fileInputKey}
                id="evidence_file"
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
                required
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
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
        {gmailDraftResult ? (
          <div className="success-box">
            <strong>Brouillon Gmail cree</strong>
            <span>{gmailDraftResult.provider_draft_id ?? gmailDraftResult.status}</span>
          </div>
        ) : null}
        {gmailSendResult ? (
          <div className="success-box">
            <strong>Email envoye depuis Gmail</strong>
            <span>{gmailSendResult.provider_message_id ?? gmailSendResult.status}</span>
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
                  <th>Gmail</th>
                  {canValidateOrDraft ? <th>Actions Gmail</th> : null}
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
                      {draft.provider_status ? (
                        <div className="stack-sm">
                          <StatusBadge status={draft.provider_status} />
                          <span className="muted">Brouillon: {draft.provider_draft_id ?? "-"}</span>
                          <span className="muted">A: {draft.provider_to_email ?? "-"}</span>
                          {draft.provider_message_id ? (
                            <span className="muted">Message: {draft.provider_message_id}</span>
                          ) : null}
                          {draft.provider_sent_at ? (
                            <span className="muted">Envoye: {formatDate(draft.provider_sent_at)}</span>
                          ) : null}
                        </div>
                      ) : (
                        "-"
                      )}
                    </td>
                    {canValidateOrDraft ? (
                      <td>
                        {!draft.provider_status ? (
                          <div className="inline-form">
                            <input
                              aria-label={`Destinataire Gmail brouillon ${draft.id}`}
                              value={getGmailForm(draft.id).to_email}
                              onChange={(event) => updateGmailForm(draft.id, { to_email: event.target.value })}
                            />
                            <label className="checkbox-row">
                              <input
                                type="checkbox"
                                checked={getGmailForm(draft.id).include_evidence}
                                onChange={(event) =>
                                  updateGmailForm(draft.id, { include_evidence: event.target.checked })
                                }
                              />
                              Preuves
                            </label>
                            <button
                              type="button"
                              className="button"
                              onClick={() => handleCreateGmailDraft(draft.id)}
                              disabled={submittingGmailDraftId === draft.id}
                            >
                              {submittingGmailDraftId === draft.id ? "Creation" : "Creer Gmail"}
                            </button>
                          </div>
                        ) : (
                          <div className="inline-form">
                            <span className="muted">Aucun email n'est envoye automatiquement.</span>
                            <span className="muted">
                              Cette action va envoyer reellement l'email depuis Gmail. Elle ne peut pas etre annulee.
                            </span>
                            <label className="checkbox-row">
                              <input
                                type="checkbox"
                                checked={sendConfirmations[draft.id] ?? false}
                                onChange={(event) =>
                                  setSendConfirmations((current) => ({
                                    ...current,
                                    [draft.id]: event.target.checked,
                                  }))
                                }
                                disabled={draft.provider_status !== "provider_draft_created"}
                              />
                              Je confirme vouloir envoyer cet email
                            </label>
                            <button
                              type="button"
                              className="danger-button"
                              onClick={() => handleSendGmailDraft(draft)}
                              disabled={
                                draft.provider_status !== "provider_draft_created" ||
                                !sendConfirmations[draft.id] ||
                                !gmailStatus?.enabled ||
                                !gmailStatus.connected ||
                                sendingProviderDraftId === draft.provider_draft_id
                              }
                            >
                              {sendingProviderDraftId === draft.provider_draft_id
                                ? "Envoi"
                                : draft.provider_status === "sent"
                                  ? "Envoye"
                                  : "Envoyer le brouillon Gmail"}
                            </button>
                            {!gmailStatus?.enabled || !gmailStatus.connected ? (
                              <span className="muted">Connexion Gmail requise.</span>
                            ) : null}
                          </div>
                        )}
                      </td>
                    ) : null}
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

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Historique email</h2>
          <span className="muted">Aucune reponse automatique</span>
        </div>
        {emailMessages && (emailMessages.threads.length > 0 || emailMessages.inbound_messages.length > 0) ? (
          <div className="stack-sm">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Direction</th>
                    <th>Sujet</th>
                    <th>Message</th>
                    <th>Date</th>
                    <th>Extrait</th>
                  </tr>
                </thead>
                <tbody>
                  {emailMessages.threads.map((thread) => (
                    <tr key={`thread-${thread.id}`}>
                      <td>
                        <StatusBadge status={thread.direction} />
                      </td>
                      <td>{thread.subject ?? "-"}</td>
                      <td>{thread.message_id ?? "-"}</td>
                      <td>{formatDate(thread.sent_at ?? thread.received_at ?? thread.created_at)}</td>
                      <td>{thread.body ? thread.body.slice(0, 180) : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3>Messages Gmail entrants rattaches</h3>
            {emailMessages.inbound_messages.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>De</th>
                      <th>Sujet</th>
                      <th>Reception</th>
                      <th>Match</th>
                      <th>Extrait</th>
                    </tr>
                  </thead>
                  <tbody>
                    {emailMessages.inbound_messages.map((message) => (
                      <tr key={`inbound-${message.id}`}>
                        <td>{message.from_email ?? "-"}</td>
                        <td>{message.subject ?? "-"}</td>
                        <td>{formatDate(message.received_at)}</td>
                        <td>
                          <div className="stack-sm">
                            <StatusBadge status={message.match_status} />
                            <span className="muted">{message.match_reason}</span>
                          </div>
                        </td>
                        <td>{message.snippet ?? message.body_text?.slice(0, 180) ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="Aucune reponse rattachee" />
            )}
          </div>
        ) : (
          <EmptyState title="Aucun historique email" />
        )}
      </section>
    </section>
  );
}

function formatDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatFileSize(value: number | null): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (value < 1024) {
    return `${value} o`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} Ko`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} Mo`;
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
