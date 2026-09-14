"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, type UberStatus } from "@/lib/api";

export default function UberPage() {
  const [status, setStatus] = useState<UberStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getUberStatus()
      .then(setStatus)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement integration Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Connecteur officiel</h1>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Connexion officielle Uber Eats</h2>
          {status ? <StatusBadge status={status.status} /> : null}
        </div>
        <div className="detail-grid">
          <DetailItem label="API officielle" value={status?.official_api_enabled ? "Connectee" : "En attente d'autorisation Uber"} />
          <DetailItem label="Identifiants API" value={status?.credentials_configured ? "Configures" : "Manquants"} />
          <DetailItem label="Surveillance annulations" value={status?.official_api_enabled ? "Webhooks + controle toutes les 3 min" : "Prete, inactive tant que Uber n'autorise pas l'app"} />
          <DetailItem label="Mode TENNET" value="Observateur passif - ne remplace pas le gestionnaire de commandes" />
          <DetailItem label="OAuth callback" value={status?.oauth_redirect_uri ?? "—"} />
          <DetailItem label="Webhook Uber" value={status?.webhook_url ?? "—"} />
        </div>

        {!status?.credentials_configured ? (
          <div className="form-grid" style={{ marginTop: 20 }}>
            <label>
              <span>Uber client ID</span>
              <input value={clientId} onChange={(event) => setClientId(event.target.value)} autoComplete="off" />
            </label>
            <label>
              <span>Uber client secret</span>
              <input
                type="password"
                value={clientSecret}
                onChange={(event) => setClientSecret(event.target.value)}
                autoComplete="new-password"
              />
            </label>
            <button
              className="button"
              disabled={saving || !clientId.trim() || !clientSecret.trim()}
              onClick={async () => {
                setSaving(true);
                setError(null);
                try {
                  const updated = await api.configureUberCredentials({
                    client_id: clientId.trim(),
                    client_secret: clientSecret.trim(),
                  });
                  setStatus(updated);
                  setClientSecret("");
                } catch (caught) {
                  setError(caught);
                } finally {
                  setSaving(false);
                }
              }}
            >
              {saving ? "Configuration..." : "Enregistrer les identifiants Uber"}
            </button>
          </div>
        ) : !status?.official_api_enabled ? (
          <div className="action-row" style={{ marginTop: 20 }}>
            <button
              className="button"
              onClick={async () => {
                setError(null);
                try {
                  const result = await api.startUberOAuth();
                  window.location.assign(result.authorization_url);
                } catch (caught) {
                  setError(caught);
                }
              }}
            >
              Autoriser mes restaurants Uber Eats
            </button>
          </div>
        ) : (
          <p style={{ marginTop: 20 }}>
            TENNET est autorise a observer les stores relies. Les annulations sont captees par webhook et par verification periodique.
          </p>
        )}
      </section>

      <div className="action-row">
        <Link className="button" href="/uber/stores">
          Mapper les stores Uber
        </Link>
        <Link className="secondary-button" href="/uber/reconciliation">
          Reconciliation
        </Link>
        <Link className="secondary-button" href="/uber/reporting">
          Reporting imports
        </Link>
        <Link className="secondary-button" href="/uber/unmapped-stores">
          Stores non mappes
        </Link>
      </div>
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
