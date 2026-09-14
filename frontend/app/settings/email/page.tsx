"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  formatDate,
  type EmailAccount,
  type GmailConnectionStatus,
  type GmailInboundStatus,
  type GmailOAuthConfig,
  type GmailRestaurantMapping,
} from "@/lib/api";

export default function EmailSettingsPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState<GmailConnectionStatus | null>(null);
  const [oauthConfig, setOauthConfig] = useState<GmailOAuthConfig | null>(null);
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthClientSecret, setOauthClientSecret] = useState("");
  const [oauthRedirectUri, setOauthRedirectUri] = useState("");
  const [inboundStatus, setInboundStatus] = useState<GmailInboundStatus | null>(null);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [mappings, setMappings] = useState<GmailRestaurantMapping[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [savingRestaurantId, setSavingRestaurantId] = useState<number | null>(null);
  const [savingOauth, setSavingOauth] = useState(false);
  const [manualAction, setManualAction] = useState<"sync" | "analyze" | null>(null);
  const [manualMessage, setManualMessage] = useState<string | null>(null);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const [gmailStatus, gmailInboundStatus, gmailAccounts, gmailMappings, gmailOauthConfig] = await Promise.all([
        api.getGmailStatus(),
        api.getInboundStatus(),
        api.getGmailAccounts(),
        api.getGmailRestaurantMappings(),
        api.getGmailOAuthConfig(),
      ]);
      setStatus(gmailStatus);
      setInboundStatus(gmailInboundStatus);
      setAccounts(gmailAccounts);
      setMappings(gmailMappings);
      setOauthConfig(gmailOauthConfig);
      setOauthClientId(gmailOauthConfig.client_id ?? "");
      const productionRedirect =
        typeof window !== "undefined"
          ? `${window.location.origin}/api/v1/email/gmail/oauth/callback`
          : gmailOauthConfig.redirect_uri;
      setOauthRedirectUri(
        !gmailOauthConfig.redirect_uri || gmailOauthConfig.redirect_uri.includes("localhost")
          ? productionRedirect
          : gmailOauthConfig.redirect_uri,
      );
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
    if (!oauthConfig?.configured) {
      setManualMessage("Configure d'abord Google OAuth dans le bloc ci-dessous.");
      return;
    }
    setConnecting(true);
    setManualMessage(null);
    setError(null);
    try {
      const response = await api.startGmailOAuth();
      window.location.href = response.authorization_url;
    } catch (apiError) {
      setError(apiError);
      setConnecting(false);
    }
  }

  async function handleSaveOauth() {
    if (!oauthClientId.trim()) {
      setManualMessage("Le Client ID Google OAuth est obligatoire.");
      return;
    }
    if (!oauthRedirectUri.trim()) {
      setManualMessage("L'URI de redirection Google OAuth est obligatoire.");
      return;
    }
    setSavingOauth(true);
    setManualMessage(null);
    setError(null);
    try {
      const updated = await api.updateGmailOAuthConfig({
        client_id: oauthClientId.trim(),
        client_secret: oauthClientSecret.trim() || null,
        redirect_uri: oauthRedirectUri.trim(),
      });
      setOauthConfig(updated);
      setOauthClientId(updated.client_id ?? "");
      setOauthClientSecret("");
      setOauthRedirectUri(updated.redirect_uri);
      setManualMessage(
        updated.configured
          ? "Configuration Google OAuth enregistree. Tu peux maintenant connecter ou reconnecter Gmail."
          : "Client ID enregistre. Il manque encore le Client Secret Google OAuth.",
      );
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSavingOauth(false);
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true);
    setManualMessage(null);
    setError(null);
    try {
      await api.disconnectGmail();
      setManualMessage("Le compte Gmail actif a ete deconnecte.");
      await loadStatus();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setDisconnecting(false);
    }
  }

  async function handleMappingChange(restaurantId: number, value: string) {
    setSavingRestaurantId(restaurantId);
    setManualMessage(null);
    setError(null);
    try {
      const accountId = value ? Number(value) : null;
      const updated = await api.updateGmailRestaurantMapping(restaurantId, accountId);
      setMappings((current) =>
        current.map((mapping) => (mapping.restaurant_id === restaurantId ? updated : mapping)),
      );
      setManualMessage("Affectation Gmail du restaurant enregistree.");
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSavingRestaurantId(null);
    }
  }

  async function handleManualSync() {
    setManualAction("sync");
    setManualMessage(null);
    setError(null);
    try {
      const result = await api.syncInboundGmail({
        lookback_days: 30,
        max_messages: 500,
        analyze_responses: true,
        apply_reviews: true,
        run_autopilot_after_sync: true,
      });
      setManualMessage(
        `Synchronisation terminee : ${result.synced_messages} messages lus, ${result.linked_messages} lies, ${result.analyzed_messages} analyses, ${result.autopilot_sent_count} envois AutoPilot.`,
      );
      await loadStatus();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setManualAction(null);
    }
  }

  async function handleManualAnalyze() {
    setManualAction("analyze");
    setManualMessage(null);
    setError(null);
    try {
      const result = await api.analyzeInboundGmail({
        apply_reviews: true,
        limit: 500,
        only_unreviewed: true,
      });
      setManualMessage(
        `Analyse terminee : ${result.analyzed_messages} messages analyses, ${result.applied_reviews} decisions appliquees, ${result.manual_review_messages} a verifier.`,
      );
      await loadStatus();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setManualAction(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement email" />;
  }

  const reconnectRequired =
    status?.connected === false || accounts.some((account) => !account.gmail_modify_enabled);
  const gmailReady = Boolean(status?.enabled && status.connected);

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Parametres / Gmail</p>
          <h1>Gmail</h1>
          <p>
            Ici tu gardes le controle manuel des comptes. TENNET continue ensuite la surveillance,
            l'analyse et les relances automatiquement.
          </p>
        </div>
        <div className="actions">
          <Link href="/settings" className="secondary-button">
            Tous les parametres
          </Link>
          <Link href="/gmail-war-room" className="secondary-button">
            War Room Gmail
          </Link>
        </div>
      </div>

      <ApiError error={error} />
      {manualMessage ? <p className="muted">{manualMessage}</p> : null}

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Configuration Google OAuth</h2>
          <StatusBadge status={oauthConfig?.configured ? "active" : "attention"} />
        </div>
        <p className="muted">
          Cette configuration appartient maintenant a TENNET. Elle ne depend plus d'une variable Vercel cachee.
          Le Client Secret est chiffre et n'est jamais reaffiche apres enregistrement.
        </p>
        <div className="detail-grid">
          <DetailItem label="Client ID" value={oauthConfig?.client_id ? "configure" : "manquant"} />
          <DetailItem
            label="Client Secret"
            value={oauthConfig?.client_secret_configured ? "configure" : "manquant"}
          />
          <DetailItem label="Redirect URI" value={oauthRedirectUri || "-"} />
        </div>
        {user?.role === "owner" ? (
          <>
            <div className="filters">
              <div className="field">
                <label htmlFor="gmail_oauth_client_id">Google OAuth Client ID</label>
                <input
                  id="gmail_oauth_client_id"
                  value={oauthClientId}
                  onChange={(event) => setOauthClientId(event.target.value)}
                  placeholder="...apps.googleusercontent.com"
                  autoComplete="off"
                />
              </div>
              <div className="field">
                <label htmlFor="gmail_oauth_client_secret">Google OAuth Client Secret</label>
                <input
                  id="gmail_oauth_client_secret"
                  type="password"
                  value={oauthClientSecret}
                  onChange={(event) => setOauthClientSecret(event.target.value)}
                  placeholder={oauthConfig?.client_secret_configured ? "Laisser vide pour conserver le secret actuel" : "Client Secret Google"}
                  autoComplete="new-password"
                />
              </div>
              <div className="field">
                <label htmlFor="gmail_oauth_redirect_uri">URI de redirection autorisee</label>
                <input
                  id="gmail_oauth_redirect_uri"
                  value={oauthRedirectUri}
                  onChange={(event) => setOauthRedirectUri(event.target.value)}
                  autoComplete="off"
                />
              </div>
            </div>
            <div className="actions">
              <button
                type="button"
                className="button"
                disabled={savingOauth}
                onClick={() => void handleSaveOauth()}
              >
                {savingOauth ? "Enregistrement..." : "Enregistrer Google OAuth"}
              </button>
            </div>
          </>
        ) : (
          <p className="muted">Seul le proprietaire TENNET peut modifier la configuration Google OAuth.</p>
        )}
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Connexion Gmail</h2>
          <StatusBadge status={!status?.enabled ? "disabled" : status.connected ? "active" : "inactive"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Provider" value={status?.provider ?? "gmail"} />
          <DetailItem
            label="Etat"
            value={!status?.enabled ? "desactive" : status.connected ? "connecte" : "non connecte"}
          />
          <DetailItem label="Compte actif" value={status?.email_address ?? "-"} />
          <DetailItem label="Comptes connectes" value={String(accounts.length)} />
        </div>
        {!status?.enabled ? (
          <p className="muted">Le provider email est desactive dans la configuration serveur.</p>
        ) : (
          <div className="actions">
            <button
              type="button"
              className="button"
              onClick={handleConnect}
              disabled={connecting || !oauthConfig?.configured}
            >
              {connecting
                ? "Ouverture de Google..."
                : reconnectRequired
                  ? "Reconnecter / ajouter un Gmail"
                  : accounts.length > 0
                    ? "Connecter un autre Gmail"
                    : "Connecter Gmail"}
            </button>
            <button
              type="button"
              className="danger-button"
              onClick={handleDisconnect}
              disabled={disconnecting || !status.connected}
            >
              {disconnecting ? "Deconnexion..." : "Deconnecter le compte actif"}
            </button>
          </div>
        )}
        <p className="muted">
          Tu peux connecter plusieurs boites Gmail l'une apres l'autre. TENNET conserve chaque compte et tu choisis ensuite
          quel Gmail gere quel restaurant. Si le bouton est desactive, termine d'abord la configuration Google OAuth ci-dessus.
        </p>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Commandes manuelles Gmail</h2>
          <StatusBadge status={gmailReady ? "active" : "inactive"} />
        </div>
        <p className="muted">
          Ces boutons sont facultatifs : ils permettent de forcer une action quand tu le souhaites sans desactiver
          l'automatisation.
        </p>
        <div className="actions">
          <button
            type="button"
            className="button"
            disabled={!gmailReady || manualAction !== null}
            onClick={() => void handleManualSync()}
          >
            {manualAction === "sync" ? "Synchronisation..." : "Synchroniser Gmail maintenant"}
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={!gmailReady || manualAction !== null}
            onClick={() => void handleManualAnalyze()}
          >
            {manualAction === "analyze" ? "Analyse..." : "Analyser les reponses maintenant"}
          </button>
          <Link href="/relance-gmail" className="secondary-button">
            Voir les relances
          </Link>
          <Link href="/inbox" className="secondary-button">
            Voir les reponses Uber
          </Link>
        </div>
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
                  <th>Droits Gmail</th>
                  <th>Connecte le</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td>{account.email_address ?? "-"}</td>
                    <td>{account.gmail_modify_enabled ? "Lecture + gestion actives" : "Reconnexion requise"}</td>
                    <td>{formatDate(account.connected_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reconnectRequired ? (
          <p className="muted">
            Un compte demande une nouvelle autorisation Google. Clique sur « Reconnecter / ajouter un Gmail » puis
            selectionne le compte concerne.
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
                        ? "Enregistrement..."
                        : mapping.email_address ?? "Defaut"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted">
          Cette affectation decide quelle boite Gmail TENNET surveille et utilise pour les relances de chaque restaurant.
        </p>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Surveillance automatique Gmail</h2>
          <StatusBadge status={!inboundStatus?.enabled ? "disabled" : inboundStatus.status ?? "idle"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Lecture automatique" value={!inboundStatus?.enabled ? "desactivee" : "activee"} />
          <DetailItem label="Derniere sync" value={formatDate(inboundStatus?.last_sync_at ?? null)} />
          <DetailItem label="Dernier succes" value={formatDate(inboundStatus?.last_success_at ?? null)} />
        </div>
        <p className="muted">
          TENNET doit surveiller les nouvelles reponses Uber, les analyser, rapprocher les dossiers et alimenter les
          relances automatiquement. Les commandes manuelles ci-dessus restent disponibles en secours ou pour controle.
        </p>
        {inboundStatus?.last_error ? <p className="muted">Derniere erreur : {inboundStatus.last_error}</p> : null}
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
