"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import ApiError from "@/components/ApiError";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await signIn({ email: email.trim(), password });
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
        <p className="eyebrow">Connexion</p>
        <h1>TENNET</h1>
      </div>

      <ApiError error={error} />

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input id="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password">Mot de passe</label>
          <input
            id="password"
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Connexion" : "Se connecter"}
          </button>
          <Link href="/setup-owner" className="secondary-button">
            Premier owner
          </Link>
        </div>
      </form>
    </section>
  );
}
