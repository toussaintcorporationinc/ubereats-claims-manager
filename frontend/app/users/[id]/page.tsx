"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type Restaurant, type User } from "@/lib/api";

export default function UserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = Number(params.id);
  const { user: currentUser } = useAuth();
  const [user, setUser] = useState<User | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantId, setRestaurantId] = useState("");
  const [removeRestaurantId, setRemoveRestaurantId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    const [userData, restaurantsData] = await Promise.all([api.getUser(userId), api.getRestaurants()]);
    setUser(userData);
    setRestaurants(restaurantsData);
  }, [userId]);

  useEffect(() => {
    if (!Number.isFinite(userId)) {
      setError(new Error("Utilisateur invalide"));
      setLoading(false);
      return;
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData, userId]);

  if (currentUser?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  async function handleAssign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setActionError(null);
    setMessage(null);

    try {
      await api.assignUserRestaurant(userId, Number(restaurantId));
      setRestaurantId("");
      setMessage("Acces restaurant assigne.");
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setActionError(null);
    setMessage(null);

    try {
      await api.removeUserRestaurant(userId, Number(removeRestaurantId));
      setRemoveRestaurantId("");
      setMessage("Acces restaurant retire.");
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement utilisateur" />;
  }

  if (!user) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Utilisateur introuvable" />
      </section>
    );
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Utilisateur</p>
          <h1>{user.email}</h1>
        </div>
        <Link href="/users" className="secondary-button">
          Retour utilisateurs
        </Link>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      {message ? <div className="success-box">{message}</div> : null}

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Profil</h2>
          <StatusBadge status={user.active ? "active" : "inactive"} />
        </div>
        <div className="detail-grid">
          <DetailItem label="Email" value={user.email} />
          <DetailItem label="Nom" value={user.full_name ?? "-"} />
          <DetailItem label="Role" value={user.role} />
        </div>
      </section>

      <section className="grid-two">
        <form className="tool-panel" onSubmit={handleAssign}>
          <h2>Assigner restaurant</h2>
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select
              id="restaurant_id"
              required
              value={restaurantId}
              onChange={(event) => setRestaurantId(event.target.value)}
            >
              <option value="">Selectionner</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={submitting}>
              Assigner
            </button>
          </div>
        </form>

        <form className="tool-panel" onSubmit={handleRemove}>
          <h2>Retirer acces</h2>
          <div className="field">
            <label htmlFor="remove_restaurant_id">Restaurant</label>
            <select
              id="remove_restaurant_id"
              required
              value={removeRestaurantId}
              onChange={(event) => setRemoveRestaurantId(event.target.value)}
            >
              <option value="">Selectionner</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="actions">
            <button type="submit" className="danger-button" disabled={submitting}>
              Retirer
            </button>
          </div>
        </form>
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
