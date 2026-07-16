"use client";

import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDate,
  type EmailAccount,
  type GmailConnectionStatus,
  type GmailInboundStatus,
  type GmailRestaurantMapping,
} from "@/lib/api";

export default function EmailSettingsPage() {
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [inboundStatus, setInboundStatus] = useState<GmailInboundStatus | null>(null);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [mappings, setMappings] = useState<GmailRestaurantMapping[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [savingRestaurantId, setSavingRestaurantId] = useState<number | null>(null);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const [gmailStatus, gmailInboundStatus, gmailAccounts, gmailMappings] = await Promise.all([
        api.getGmailStatus(),
        api.getInboundStatus(),
        api.getGmailAccounts(),
        api.getGmailRestaurantMappings(),
      ]);
      setStatus(gmailStatus);
      setInboundStatus(gmailInboundStatus);
      setAccounts(gmailAccounts);
      setMappings(gmailMappings);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  async function handleConnect() {
    setConnecting(true);
    setError(null);

    try {
      const response = await api.startGmailOAuth();
      window.location.href = response.authorization_url;
    } catch (apiError) {
      setError(apiError);
      setConnecting(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    setError(null);

    try {
      await api.disconnectGmail();
      await loadStatus();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setDisconnecting(false);
    }
  }

  async function handleMappingChange(restaurantId: number, value: string) {
    setSavingRestaurantId(restaurantId);
    setError(null);
    try {
      const accountId = value ? Number(value) : null;
      const updated = await api.updateGmailRestaurantMapping(restaurantId, accountId);
      setMappings((current) => current.map((mapping) => (mapping.restaurant_id === restaurantId ? updated : mapping)));
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSavingRestaurantId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement email" />;
  }

  const reconnectRequired = accounts.some((account) => !account.gmail_modify_enabled);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Email</p>
          <h1>Parametres Gmail</h1>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Connexion Gmail</h2>
          <StatusBadge status={!status?.enabled ? "disabled" : status.connected ? "active" : "inactive"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Provider" value={status?.provider ?? "gmail"} />
          <DetailItem label="Etat" value={!status?.enabled ? "desactive" : status.connected ? "connecte" : "non connecte"} />
          <DetailItem label="Compte" value={status?.email_address ?? "-"} />
        </div>
        {!status?.enabled ? (
          <p className="muted">Le provider email est desactive dans la configuration serveur.</p>
        ) : (
          <div className="actions">
            <button type="button" className="button" onClick={handleConnect} disabled={connecting}>
              {connecting
                ? "Connexion"
                : reconnectRequired
                  ? "Reconnecter Gmail"
                  : status.connected
                    ? "Connecter un autre Gmail"
                    : "Connecter Gmail"}
            </button>
            <button
              type="button"
              className="danger-button"
              onClick={handleDisconnect}
              disabled={disconnecting || !status.connected}
            >
              {disconnecting ? "Deconnexion" : "Deconnecter Gmail"}
            </button>
          </div>
        )}
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Comptes Gmail connectes</h2>
          <StatusBadge status={accounts.length > 0 ? "active" : "inactive"} />
        </div>
        {accounts.length === 0 ? (
          <p className="muted">Aucun compte Gmail connecte.</p>
        ) : (
          <div className="responsive-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Compte</th>
                  <th>Gestion des etoiles</th>
                  <th>Connecte le</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td>{account.email_address ?? "-"}</td>
                    <td>{account.gmail_modify_enabled ? "Active" : "Reconnexion requise"}</td>
                    <td>{formatDate(account.connected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted">
          TENNET peut connecter plusieurs boites Gmail. Le compte utilise pour un dossier est choisi selon le
          restaurant ci-dessous.
        </p>
        {reconnectRequired ? (
          <p className="muted">
            Reconnectez chaque compte signale pour autoriser TENNET a retirer les etoiles apres un paiement positif.
          </p>
        ) : null}
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Gmail par restaurant</h2>
          <StatusBadge status={mappings.some((mapping) => mapping.email_account_id) ? "active" : "manual_review"} />
        </div>
        {mappings.length === 0 ? (
          <p className="muted">Aucun restaurant visible pour cet utilisateur.</p>
        ) : (
          <div className="responsive-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Restaurant</th>
                  <th>Compte Gmail</th>
                  <th>Etat</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((mapping) => (
                  <tr key={mapping.restaurant_id}>
                    <td>{mapping.restaurant_name}</td>
                    <td>
                      <select
                        value={mapping.email_account_id ?? ""}
                        onChange={(event) => void handleMappingChange(mapping.restaurant_id, event.target.value)}
                        disabled={savingRestaurantId === mapping.restaurant_id || accounts.length === 0}
                      >
                        <option value="">Compte actif par defaut</option>
                        {accounts.map((account) => (
                          <option key={account.id} value={account.id}>
                            {account.email_address ?? `Compte #${account.id}`}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      {savingRestaurantId === mapping.restaurant_id
                        ? "Enregistrement"
                        : mapping.email_address ?? "Defaut"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted">
          Assignez chaque restaurant au compte Gmail qui gere ses conversations Uber. Les comptes affiches ici sont les
          comptes reellement connectes dans TENNET.
        </p>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Lecture reponses Gmail</h2>
          <StatusBadge status={!inboundStatus?.enabled ? "disabled" : inboundStatus.status ?? "idle"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Sync inbound" value={!inboundStatus?.enabled ? "desactivee" : "activee"} />
          <DetailItem label="Derniere sync" value={formatDate(inboundStatus?.last_sync_at ?? null)} />
          <DetailItem label="Dernier succes" value={formatDate(inboundStatus?.last_success_at ?? null)} />
        </div>
        <p className="muted">
          La lecture requiert gmail.readonly et le retrait des etoiles requiert gmail.modify. Les anciens comptes
          doivent etre reconnectes une fois pour accorder les deux droits.
        </p>
        {inboundStatus?.last_error ? <p className="muted">Derniere erreur: {inboundStatus.last_error}</p> : null}
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
