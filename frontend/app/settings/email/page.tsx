"use client";

import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatDate, type GmailConnectionStatus, type GmailInboundStatus } from "@/lib/api";

export default function EmailSettingsPage() {
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [inboundStatus, setInboundStatus] = useState<GmailInboundStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const [gmailStatus, gmailInboundStatus] = await Promise.all([api.getGmailStatus(), api.getInboundStatus()]);
      setStatus(gmailStatus);
      setInboundStatus(gmailInboundStatus);
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

  if (loading) {
    return <LoadingState label="Chargement email" />;
  }

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
              {connecting ? "Connexion" : "Connecter Gmail"}
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
          <h2>Lecture reponses Gmail</h2>
          <StatusBadge status={!inboundStatus?.enabled ? "disabled" : inboundStatus.status ?? "idle"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Sync inbound" value={!inboundStatus?.enabled ? "desactivee" : "activee"} />
          <DetailItem label="Derniere sync" value={formatDate(inboundStatus?.last_sync_at ?? null)} />
          <DetailItem label="Dernier succes" value={formatDate(inboundStatus?.last_success_at ?? null)} />
        </div>
        <p className="muted">
          La lecture Gmail requiert le scope gmail.readonly. Les comptes connectes avant ce changement peuvent devoir
          se reconnecter pour autoriser la lecture des reponses.
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
