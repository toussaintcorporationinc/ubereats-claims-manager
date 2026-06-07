"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import ApiError from "@/components/ApiError";
import { useAuth } from "@/lib/auth";

export default function SetupOwnerPage() {
  const router = useRouter();
  const { setupOwner } = useAuth();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await setupOwner({
        email: email.trim(),
        password,
        full_name: fullName.trim() || null,
      });
      router.replace("/dashboard");
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-panel">
      <div className="heading-copy">
        <p className="eyebrow">Initialisation</p>
        <h1>Creer le premier owner</h1>
      </div>

      <ApiError error={error} />

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="full_name">Nom complet</label>
          <input id="full_name" value={fullName} onChange={(event) => setFullName(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">Mot de passe</label>
          <input
            id="password"
            required
            minLength={8}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Creation" : "Creer owner"}
          </button>
          <Link href="/login" className="secondary-button">
            Connexion
          </Link>
        </div>
      </form>
    </section>
  );
}
