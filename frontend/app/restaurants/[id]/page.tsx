"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
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

function restaurantToForm(restaurant: Restaurant): RestaurantForm {
  return {
    name: restaurant.name,
    legal_name: restaurant.legal_name ?? "",
    address: restaurant.address ?? "",
    sender_email: restaurant.sender_email,
    uber_merchant_id: restaurant.uber_merchant_id ?? "",
    active: restaurant.active,
    autopilot_enabled: restaurant.autopilot_enabled,
  };
}

export default function EditRestaurantPage() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const restaurantId = Number(params.id);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [form, setForm] = useState<RestaurantForm | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(restaurantId)) {
      setError(new Error("Restaurant invalide."));
      setLoading(false);
      return;
    }

    api
      .getRestaurant(restaurantId)
      .then((data) => {
        setRestaurant(data);
        setForm(restaurantToForm(data));
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, [restaurantId]);

  if (user?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  if (loading) {
    return <LoadingState label="Chargement du restaurant" />;
  }

  if (!form || !restaurant) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Restaurant introuvable" />
      </section>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form) {
      return;
    }

    setSubmitting(true);
    setError(null);
    setSaved(false);

    try {
      const updated = await api.updateRestaurant(restaurantId, {
        name: form.name.trim(),
        legal_name: emptyToNull(form.legal_name),
        address: emptyToNull(form.address),
        sender_email: form.sender_email.trim(),
        uber_merchant_id: emptyToNull(form.uber_merchant_id),
        active: form.active,
        autopilot_enabled: form.autopilot_enabled,
      });
      setRestaurant(updated);
      setForm(restaurantToForm(updated));
      setSaved(true);
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
          <h1>Modifier restaurant</h1>
        </div>
        <div className="actions">
          <Link href="/restaurants" className="secondary-button">
            Retour restaurants
          </Link>
        </div>
      </div>

      <ApiError error={error} />

      {saved ? (
        <div className="success-box">
          <strong>Restaurant mis a jour</strong>
          <span>{restaurant.name}</span>
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
              onChange={(event) => setForm((current) => (current ? { ...current, name: event.target.value } : current))}
            />
          </div>
          <div className="field">
            <label htmlFor="legal_name">Raison sociale</label>
            <input
              id="legal_name"
              value={form.legal_name}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, legal_name: event.target.value } : current))
              }
            />
          </div>
          <div className="field field--full">
            <label htmlFor="address">Adresse</label>
            <textarea
              id="address"
              value={form.address}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, address: event.target.value } : current))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="sender_email">Email expediteur Gmail</label>
            <input
              id="sender_email"
              required
              type="email"
              value={form.sender_email}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, sender_email: event.target.value } : current))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="uber_merchant_id">Uber merchant</label>
            <input
              id="uber_merchant_id"
              value={form.uber_merchant_id}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, uber_merchant_id: event.target.value } : current))
              }
            />
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(event) => setForm((current) => (current ? { ...current, active: event.target.checked } : current))}
            />
            Restaurant actif
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.autopilot_enabled}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, autopilot_enabled: event.target.checked } : current))
              }
            />
            AutoPilot active pour ce restaurant
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Enregistrement" : "Enregistrer"}
          </button>
          <button type="button" className="secondary-button" onClick={() => router.push("/restaurants")}>
            Annuler
          </button>
        </div>
      </form>
    </section>
  );
}
