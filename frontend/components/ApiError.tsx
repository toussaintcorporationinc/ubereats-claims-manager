"use client";

import Link from "next/link";
import { ApiError as ApiErrorModel, SESSION_EXPIRED_MESSAGE } from "@/lib/api";

export default function ApiError({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  const rawMessage = error instanceof Error ? error.message : "Erreur API";
  const status = error instanceof ApiErrorModel ? error.status : null;
  const detail = error instanceof ApiErrorModel ? error.detail : null;
  const detailText = typeof detail === "string" ? detail : "";
  const searchable = `${rawMessage} ${detailText}`.toLowerCase();
  const isUnauthorized = status === 401;
  const gmailDisconnected = searchable.includes("gmail_account_not_connected");
  const gmailOauthMissing =
    searchable.includes("gmail_oauth_not_configured") ||
    searchable.includes("gmail_oauth_client_secret_not_configured");
  const unreadableLegacyToken = searchable.includes("encrypted token integrity check failed");

  let message = rawMessage;
  if (gmailDisconnected) {
    message = "Aucun Gmail utilisable n'est connecte. Ouvre Parametres > Gmail pour connecter ou reconnecter le compte.";
  } else if (gmailOauthMissing) {
    message = "La configuration Google OAuth de TENNET est incomplete. Ouvre Parametres > Gmail pour la terminer.";
  } else if (unreadableLegacyToken) {
    message = "L'ancienne autorisation Gmail n'est plus lisible. Reconnecte ce Gmail depuis Parametres > Gmail.";
  }

  const showGmailSettings = gmailDisconnected || gmailOauthMissing || unreadableLegacyToken;

  return (
    <div className="api-error" role="alert">
      <strong>{status ? `Erreur ${status}` : "Erreur"}</strong>
      <span>{isUnauthorized ? SESSION_EXPIRED_MESSAGE : message}</span>
      {isUnauthorized ? (
        <Link href="/login" className="secondary-button">
          Se reconnecter
        </Link>
      ) : null}
      {!isUnauthorized && showGmailSettings ? (
        <Link href="/settings/email" className="secondary-button">
          Ouvrir Parametres Gmail
        </Link>
      ) : null}
      {!isUnauthorized && !showGmailSettings && detail && typeof detail === "object" ? (
        <pre>{JSON.stringify(detail, null, 2)}</pre>
      ) : null}
    </div>
  );
}
