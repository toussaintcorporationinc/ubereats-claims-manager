"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, formatDate, type EmailDraftSummary } from "@/lib/api";

const defaultRecipient = "merchants@uber.com";

type GmailDraftForm = {
  to_email: string;
  include_evidence: boolean;
};

export default function DraftsPage() {
  const { user } = useAuth();
  const [drafts, setDrafts] = useState<EmailDraftSummary[]>([]);
  const [gmailForms, setGmailForms] = useState<Record<number, GmailDraftForm>>({});
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submittingDraftId, setSubmittingDraftId] = useState<number | null>(null);

  const canCreateGmailDraft = user?.role === "owner" || user?.role === "manager";

  const loadDrafts = useCallback(async () => {
    setDrafts(await api.getDrafts());
  }, []);

  useEffect(() => {
    loadDrafts()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadDrafts]);

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
                {canCreateGmailDraft ? <th>Creation Gmail</th> : null}
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
                        <span className="muted">{draft.provider_draft_id ?? "-"}</span>
                      </div>
                    ) : (
                      "-"
                    )}
                  </td>
                  {canCreateGmailDraft ? (
                    <td>
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
                          disabled={
                            submittingDraftId === draft.id || draft.provider_status === "provider_draft_created"
                          }
                        >
                          {submittingDraftId === draft.id ? "Creation" : "Creer Gmail"}
                        </button>
                      </div>
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
