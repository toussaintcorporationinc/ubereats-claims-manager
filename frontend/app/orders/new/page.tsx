"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import { api, emptyToNull, type ClaimOrder, type Restaurant } from "@/lib/api";

type OrderForm = {
  restaurant_id: string;
  internal_reference: string;
  uber_order_number: string;
  customer_name: string;
  order_date: string;
  order_time: string;
  cancellation_time: string;
  order_amount: string;
  currency: string;
  accepted_by_restaurant: string;
  prepared_before_cancellation: string;
  loss_type: string;
  notes: string;
};

const initialForm: OrderForm = {
  restaurant_id: "",
  internal_reference: "",
  uber_order_number: "",
  customer_name: "",
  order_date: "",
  order_time: "",
  cancellation_time: "",
  order_amount: "",
  currency: "EUR",
  accepted_by_restaurant: "",
  prepared_before_cancellation: "",
  loss_type: "",
  notes: "",
};

export default function NewOrderPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [form, setForm] = useState<OrderForm>(initialForm);
  const [createdOrder, setCreatedOrder] = useState<ClaimOrder | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .getRestaurants()
      .then(setRestaurants)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setCreatedOrder(null);

    try {
      const order = await api.createOrder({
        restaurant_id: Number(form.restaurant_id),
        internal_reference: emptyToNull(form.internal_reference),
        uber_order_number: form.uber_order_number.trim(),
        customer_name: emptyToNull(form.customer_name),
        order_date: emptyToNull(form.order_date),
        order_time: emptyToNull(form.order_time),
        cancellation_time: emptyToNull(form.cancellation_time),
        order_amount: form.order_amount.trim(),
        currency: form.currency.trim() || "EUR",
        accepted_by_restaurant: parseOptionalBoolean(form.accepted_by_restaurant),
        prepared_before_cancellation: parseOptionalBoolean(form.prepared_before_cancellation),
        loss_type: emptyToNull(form.loss_type),
        notes: emptyToNull(form.notes),
      });
      setCreatedOrder(order);
      setForm(initialForm);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du formulaire" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Commandes</p>
          <h1>Nouvelle commande</h1>
        </div>
        <Link href="/orders" className="secondary-button">
          Retour commandes
        </Link>
      </div>

      <ApiError error={error} />

      {createdOrder ? (
        <div className="success-box">
          <strong>Commande creee</strong>
          <span>{createdOrder.uber_order_number}</span>
          <div className="actions">
            <Link href={`/orders/${createdOrder.id}`} className="button">
              Ouvrir detail
            </Link>
            <Link href="/orders" className="secondary-button">
              Liste commandes
            </Link>
          </div>
        </div>
      ) : null}

      {restaurants.length > 0 ? (
        <form className="tool-panel" onSubmit={handleSubmit}>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="restaurant_id">Restaurant</label>
              <select
                id="restaurant_id"
                required
                value={form.restaurant_id}
                onChange={(event) => setForm((current) => ({ ...current, restaurant_id: event.target.value }))}
              >
                <option value="">Selectionner</option>
                {restaurants.map((restaurant) => (
                  <option key={restaurant.id} value={restaurant.id}>
                    {restaurant.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="internal_reference">Reference interne</label>
              <input
                id="internal_reference"
                value={form.internal_reference}
                onChange={(event) => setForm((current) => ({ ...current, internal_reference: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="uber_order_number">Numero commande Uber</label>
              <input
                id="uber_order_number"
                required
                value={form.uber_order_number}
                onChange={(event) => setForm((current) => ({ ...current, uber_order_number: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="customer_name">Client</label>
              <input
                id="customer_name"
                value={form.customer_name}
                onChange={(event) => setForm((current) => ({ ...current, customer_name: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="order_date">Date</label>
              <input
                id="order_date"
                type="date"
                value={form.order_date}
                onChange={(event) => setForm((current) => ({ ...current, order_date: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="order_time">Heure commande</label>
              <input
                id="order_time"
                type="time"
                value={form.order_time}
                onChange={(event) => setForm((current) => ({ ...current, order_time: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="cancellation_time">Heure annulation</label>
              <input
                id="cancellation_time"
                type="time"
                value={form.cancellation_time}
                onChange={(event) => setForm((current) => ({ ...current, cancellation_time: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="order_amount">Montant</label>
              <input
                id="order_amount"
                required
                inputMode="decimal"
                value={form.order_amount}
                onChange={(event) => setForm((current) => ({ ...current, order_amount: event.target.value }))}
              />
            </div>
            <div className="field">
              <label htmlFor="currency">Devise</label>
              <input
                id="currency"
                required
                minLength={3}
                maxLength={3}
                value={form.currency}
                onChange={(event) => setForm((current) => ({ ...current, currency: event.target.value.toUpperCase() }))}
              />
            </div>
            <div className="field">
              <label htmlFor="accepted_by_restaurant">Acceptee par le restaurant</label>
              <select
                id="accepted_by_restaurant"
                value={form.accepted_by_restaurant}
                onChange={(event) =>
                  setForm((current) => ({ ...current, accepted_by_restaurant: event.target.value }))
                }
              >
                <option value="">Non renseigne</option>
                <option value="true">Oui</option>
                <option value="false">Non</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="prepared_before_cancellation">Preparee avant annulation</label>
              <select
                id="prepared_before_cancellation"
                value={form.prepared_before_cancellation}
                onChange={(event) =>
                  setForm((current) => ({ ...current, prepared_before_cancellation: event.target.value }))
                }
              >
                <option value="">Non renseigne</option>
                <option value="true">Oui</option>
                <option value="false">Non</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="loss_type">Type de perte</label>
              <input
                id="loss_type"
                value={form.loss_type}
                onChange={(event) => setForm((current) => ({ ...current, loss_type: event.target.value }))}
              />
            </div>
            <div className="field field--full">
              <label htmlFor="notes">Notes</label>
              <textarea
                id="notes"
                value={form.notes}
                onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
              />
            </div>
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Creation" : "Creer commande"}
            </button>
          </div>
        </form>
      ) : (
        <EmptyState title="Aucun restaurant" />
      )}
    </section>
  );
}

function parseOptionalBoolean(value: string): boolean | null {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return null;
}
