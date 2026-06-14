"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, formatDate, type EmailDraftSummary, type GmailConnectionStatus } from "@/lib/api";

const defaultRecipient = "restaurantsfrance@uber.com";

type GmailDraftForm = {
  to_email: string;
  include_evidence: boolean;
};

export default function DraftsPage() {
  const { user } = useAuth();
  const [drafts, setDrafts] = useState<EmailDraftSummary[]>([]);
  const [gmailStatus, setGmailStatus] = useState<GmailConnectionStatus | null>(null);
  const [gmailForms, setGmailForms] = useState<Record<number, GmailDraftForm>>({});
  const [sendConfirmations, setSendConfirmations] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submittingDraftId, setSubmittingDraftId] = useState<number | null>(null);
  const [sendingProviderDraftId, setSendingProviderDraftId] = useState<string | null>(null);

  const canCreateGmailDraft = user?.role === "owner" || user?.role === "manager";

  const loadDrafts = useCallback(async () => {
    setDrafts(await api.getDrafts());
  }, []);

  useEffect(() => {
    async function loadData() {
      await loadDrafts();
      if (canCreateGmailDraft) {
        setGmailStatus(await api.getGmailStatus());
      }
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [canCreateGmailDraft, loadDrafts]);

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
    setSubmittingDraftId(draftId);
    setActionError(null);

    try {
      const form = getGmailForm(draftId);
      await api.createGmailDraft(draftId, {
        to_email: form.to_email,
        include_evidence: form.include_evidence,
      });
      await loadDrafts();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmittingDraftId(null);
    }
  }

  async function handleSendGmailDraft(draft: EmailDraftSummary) {
    if (!draft.provider_draft_id) {
      return;
    }
    setSendingProviderDraftId(draft.provider_draft_id);
    setActionError(null);

    try {
      await api.sendGmailProviderDraft(draft.provider_draft_id, { confirm_send: true });
      await loadDrafts();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSendingProviderDraftId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des brouillons" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Brouillons</p>
          <h1>Brouillons internes</h1>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      {drafts.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Commande</th>
                <th>Restaurant</th>
                <th>Numero Uber</th>
                <th>Type</th>
                <th>Sujet</th>
                <th>Statut</th>
                <th>Gmail</th>
                {canCreateGmailDraft ? <th>Actions Gmail</th> : null}
                <th>Creation</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((draft) => (
                <tr key={draft.id}>
                  <td>#{draft.order_id}</td>
                  <td>{draft.restaurant_name ?? "-"}</td>
                  <td>{draft.uber_order_number ?? "-"}</td>
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
                  {canCreateGmailDraft ? (
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
                            disabled={submittingDraftId === draft.id}
                          >
                            {submittingDraftId === draft.id ? "Creation" : "Creer Gmail"}
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
                  <td>{formatDate(draft.created_at)}</td>
                  <td>
                    <Link href={`/orders/${draft.order_id}`} className="secondary-button">
                      Ouvrir
                    </Link>
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
  );
}
