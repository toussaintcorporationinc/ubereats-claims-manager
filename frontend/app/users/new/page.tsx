"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import { useAuth } from "@/lib/auth";
import { api, emptyToNull, type User, type UserRole } from "@/lib/api";

type UserForm = {
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
  active: boolean;
};

const initialForm: UserForm = {
  email: "",
  password: "",
  full_name: "",
  role: "manager",
  active: true,
};

export default function NewUserPage() {
  const { user } = useAuth();
  const [form, setForm] = useState<UserForm>(initialForm);
  const [createdUser, setCreatedUser] = useState<User | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreatedUser(null);

    try {
      const newUser = await api.createUser({
        email: form.email.trim(),
        password: form.password,
        full_name: emptyToNull(form.full_name),
        role: form.role,
        active: form.active,
      });
      setCreatedUser(newUser);
      setForm(initialForm);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Utilisateurs</p>
          <h1>Nouvel utilisateur</h1>
        </div>
        <Link href="/users" className="secondary-button">
          Retour utilisateurs
        </Link>
      </div>

      <ApiError error={error} />

      {createdUser ? (
        <div className="success-box">
          <strong>Utilisateur cree</strong>
          <span>{createdUser.email}</span>
          <div className="actions">
            <Link href={`/users/${createdUser.id}`} className="button">
              Assigner restaurants
            </Link>
            <Link href="/users" className="secondary-button">
              Liste utilisateurs
            </Link>
          </div>
        </div>
      ) : null}

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              required
              type="email"
              value={form.email}
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Mot de passe</label>
            <input
              id="password"
              required
              minLength={8}
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="full_name">Nom complet</label>
            <input
              id="full_name"
              value={form.full_name}
              onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="role">Role</label>
            <select
              id="role"
              value={form.role}
              onChange={(event) => setForm((current) => ({ ...current, role: event.target.value as UserRole }))}
            >
              <option value="manager">manager</option>
              <option value="staff">staff</option>
              <option value="owner">owner</option>
            </select>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(event) => setForm((current) => ({ ...current, active: event.target.checked }))}
            />
            Actif
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Creation" : "Creer utilisateur"}
          </button>
        </div>
      </form>
    </section>
  );
}
