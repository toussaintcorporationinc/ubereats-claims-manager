"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import { useAuth } from "@/lib/auth";
import { api, emptyToNull, type Restaurant } from "@/lib/api";

type RestaurantForm = {
  name: string;
  legal_name: string;
  address: string;
  sender_email: string;
  uber_merchant_id: string;
  active: boolean;
  autopilot_enabled: boolean;
};

const initialForm: RestaurantForm = {
  name: "",
  legal_name: "",
  address: "",
  sender_email: "",
  uber_merchant_id: "",
  active: true,
  autopilot_enabled: false,
};

export default function NewRestaurantPage() {
  const { user } = useAuth();
  const [form, setForm] = useState<RestaurantForm>(initialForm);
  const [createdRestaurant, setCreatedRestaurant] = useState<Restaurant | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreatedRestaurant(null);

    try {
      const restaurant = await api.createRestaurant({
        name: form.name.trim(),
        legal_name: emptyToNull(form.legal_name),
        address: emptyToNull(form.address),
        sender_email: form.sender_email.trim(),
        uber_merchant_id: emptyToNull(form.uber_merchant_id),
        active: form.active,
        autopilot_enabled: form.autopilot_enabled,
      });
      setCreatedRestaurant(restaurant);
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
          <p className="eyebrow">Restaurants</p>
          <h1>Nouveau restaurant</h1>
        </div>
        <Link href="/restaurants" className="secondary-button">
          Retour restaurants
        </Link>
      </div>

      <ApiError error={error} />

      {createdRestaurant ? (
        <div className="success-box">
          <strong>Restaurant cree</strong>
          <span>{createdRestaurant.name}</span>
          <div className="actions">
            <Link href={`/restaurants/${createdRestaurant.id}`} className="button">
              Configurer Gmail et Uber
            </Link>
            <Link href="/restaurants" className="secondary-button">
              Liste restaurants
            </Link>
          </div>
        </div>
      ) : null}

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="name">Nom</label>
            <input
              id="name"
              required
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="legal_name">Raison sociale</label>
            <input
              id="legal_name"
              value={form.legal_name}
              onChange={(event) => setForm((current) => ({ ...current, legal_name: event.target.value }))}
            />
          </div>
          <div className="field field--full">
            <label htmlFor="address">Adresse</label>
            <textarea
              id="address"
              value={form.address}
              onChange={(event) => setForm((current) => ({ ...current, address: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="sender_email">Email fallback du restaurant</label>
            <input
              id="sender_email"
              required
              type="email"
              value={form.sender_email}
              onChange={(event) => setForm((current) => ({ ...current, sender_email: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="uber_merchant_id">Uber merchant</label>
            <input
              id="uber_merchant_id"
              value={form.uber_merchant_id}
              onChange={(event) => setForm((current) => ({ ...current, uber_merchant_id: event.target.value }))}
            />
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(event) => setForm((current) => ({ ...current, active: event.target.checked }))}
            />
            Actif
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.autopilot_enabled}
              onChange={(event) => setForm((current) => ({ ...current, autopilot_enabled: event.target.checked }))}
            />
            AutoPilot active pour ce restaurant
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Creation" : "Creer restaurant"}
          </button>
        </div>
      </form>
    </section>
  );
}
