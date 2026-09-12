"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";
import BrandLogo from "@/components/BrandLogo";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_STORAGE_KEY = "ubereats_claims_manager_token";
const REFRESH_TOKEN_STORAGE_KEY = "ubereats_claims_manager_refresh_token";

type TokenResponse = {
  access_token: string;
  refresh_token: string;
};

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const hasToken = useMemo(() => token.length > 0, [token]);

  const [email, setEmail] = useState("toussaintcorporation@gmail.com");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function requestReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`${API_BASE_URL}/v1/auth/password-reset/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail ?? "Impossible d'envoyer l'e-mail de réinitialisation.");
      }
      setMessage("Lien de réinitialisation envoyé. Vérifiez votre boîte e-mail.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur pendant la demande de réinitialisation.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);

    if (password.length < 12) {
      setError("Le mot de passe doit contenir au moins 12 caractères.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Les deux mots de passe ne correspondent pas.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await fetch(`${API_BASE_URL}/v1/auth/password-reset/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail ?? "Impossible de réinitialiser le mot de passe.");
      }

      const auth = body as TokenResponse;
      window.localStorage.setItem(TOKEN_STORAGE_KEY, auth.access_token);
      window.localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, auth.refresh_token);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur pendant la réinitialisation.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-panel">
      <div className="heading-copy">
        <BrandLogo compact />
        <p className="eyebrow">Sécurité</p>
        <h1>Réinitialiser le mot de passe</h1>
      </div>

      {error ? (
        <div className="api-error" role="alert">
          <strong>Erreur</strong>
          <span>{error}</span>
        </div>
      ) : null}

      {message ? (
        <div className="api-error" role="status">
          <strong>Demande envoyée</strong>
          <span>{message}</span>
        </div>
      ) : null}

      {hasToken ? (
        <form className="tool-panel" onSubmit={confirmReset}>
          <div className="field">
            <label htmlFor="password">Nouveau mot de passe</label>
            <input
              id="password"
              required
              minLength={12}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="field">
            <label htmlFor="confirm_password">Confirmer le mot de passe</label>
            <input
              id="confirm_password"
              required
              minLength={12}
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Réinitialisation…" : "Réinitialiser et se connecter"}
            </button>
          </div>
        </form>
      ) : (
        <form className="tool-panel" onSubmit={requestReset}>
          <div className="field">
            <label htmlFor="email">Email owner</label>
            <input
              id="email"
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
            />
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Envoi…" : "Envoyer le lien sécurisé"}
            </button>
            <Link href="/login" className="secondary-button">
              Retour connexion
            </Link>
          </div>
        </form>
      )}
    </section>
  );
}
