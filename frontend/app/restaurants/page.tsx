"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type GmailRestaurantMapping, type Restaurant, type UberStoreMapping } from "@/lib/api";

export default function RestaurantsPage() {
  const { user } = useAuth();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [gmailMappings, setGmailMappings] = useState<GmailRestaurantMapping[]>([]);
  const [uberMappings, setUberMappings] = useState<UberStoreMapping[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [updatingRestaurantId, setUpdatingRestaurantId] = useState<number | null>(null);

  useEffect(() => {
    async function loadData() {
      const [restaurantData, gmailData, uberData] = await Promise.all([
        api.getRestaurants({ include_inactive: true }),
        api.getGmailRestaurantMappings().catch(() => [] as GmailRestaurantMapping[]),
        api.getUberStoreMappings().catch(() => [] as UberStoreMapping[]),
      ]);
      setRestaurants(restaurantData);
      setGmailMappings(gmailData);
      setUberMappings(uberData);
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function toggleAutopilot(restaurant: Restaurant) {
    setUpdatingRestaurantId(restaurant.id);
    setError(null);
    try {
      const updated = await api.updateRestaurant(restaurant.id, {
        autopilot_enabled: !restaurant.autopilot_enabled,
      });
      setRestaurants((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (apiError) {
      setError(apiError);
    } finally {
      setUpdatingRestaurantId(null);
    }
  }

  async function archiveRestaurant(restaurant: Restaurant) {
    if (!window.confirm(`Retirer ${restaurant.name} des pages TENNET ? L'historique reste conserve.`)) {
      return;
    }
    setUpdatingRestaurantId(restaurant.id);
    setError(null);
    try {
      const updated = await api.archiveRestaurant(restaurant.id);
      setRestaurants((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (apiError) {
      setError(apiError);
    } finally {
      setUpdatingRestaurantId(null);
    }
  }

  async function restoreRestaurant(restaurant: Restaurant) {
    setUpdatingRestaurantId(restaurant.id);
    setError(null);
    try {
      const updated = await api.restoreRestaurant(restaurant.id);
      setRestaurants((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (apiError) {
      setError(apiError);
    } finally {
      setUpdatingRestaurantId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement des restaurants" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Restaurants</p>
          <h1>Restaurants</h1>
        </div>
        {user?.role === "owner" ? (
          <Link href="/restaurants/new" className="button">
            Creer restaurant
          </Link>
        ) : null}
      </div>

      <ApiError error={error} />

      {restaurants.filter((restaurant) => restaurant.active).length > 0 ? (
        <div className="restaurant-card-grid">
          {restaurants.filter((restaurant) => restaurant.active).map((restaurant) => {
            const gmailMapping = gmailMappings.find((mapping) => mapping.restaurant_id === restaurant.id);
            const stores = uberMappings.filter((mapping) => mapping.restaurant_id === restaurant.id);
            return (
              <article className="restaurant-card" key={restaurant.id}>
                <div className="card-row">
                  <div className="stack-sm">
                    <h2>{restaurant.name}</h2>
                    <span className="muted">{restaurant.legal_name ?? "Raison sociale non renseignee"}</span>
                  </div>
                  <StatusBadge status={restaurant.active ? "active" : "inactive"} />
                </div>

                <div className="detail-grid detail-grid--compact">
                  <DetailItem label="Adresse" value={restaurant.address ?? "-"} />
                  <DetailItem label="Telephone" value={restaurant.phone_number ?? "-"} />
                  <DetailItem label="Email restaurant" value={restaurant.sender_email} />
                  <DetailItem label="Compte Gmail lie" value={gmailMapping?.email_address ?? "Aucun compte choisi"} />
                  <DetailItem label="Uber merchant" value={restaurant.uber_merchant_id ?? "-"} />
                  <DetailItem label="Stores Uber lies" value={stores.length > 0 ? stores.map((store) => store.uber_store_name).join(", ") : "Aucun"} />
                  <div className="detail-item">
                    <span>AutoPilot</span>
                    <div className="actions">
                      <StatusBadge status={restaurant.autopilot_enabled ? "active" : "inactive"} />
                    </div>
                  </div>
                </div>

                <div className="actions">
                  {user?.role === "owner" ? (
                    <>
                      <Link href={`/restaurants/${restaurant.id}`} className="button">
                        Modifier et mapper
                      </Link>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={updatingRestaurantId === restaurant.id}
                        onClick={() => void toggleAutopilot(restaurant)}
                      >
                        {restaurant.autopilot_enabled ? "Desactiver AutoPilot" : "Activer AutoPilot"}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={updatingRestaurantId === restaurant.id}
                        onClick={() => void archiveRestaurant(restaurant)}
                      >
                        Retirer
                      </button>
                    </>
                  ) : (
                    <span className="muted">Lecture seule</span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState title="Aucun restaurant actif" description="Cree un restaurant ou restaure un restaurant archive." />
      )}

      {user?.role === "owner" && restaurants.some((restaurant) => !restaurant.active) ? (
        <details className="simple-details">
          <summary>Restaurants archives</summary>
          <div className="restaurant-card-grid">
            {restaurants
              .filter((restaurant) => !restaurant.active)
              .map((restaurant) => (
                <article className="restaurant-card restaurant-card--archived" key={restaurant.id}>
                  <div className="card-row">
                    <div className="stack-sm">
                      <h2>{restaurant.name}</h2>
                      <span className="muted">Historique conserve, masque des pages operationnelles.</span>
                    </div>
                    <StatusBadge status="inactive" />
                  </div>
                  <div className="detail-grid detail-grid--compact">
                    <DetailItem label="Adresse" value={restaurant.address ?? "-"} />
                    <DetailItem label="Telephone" value={restaurant.phone_number ?? "-"} />
                    <DetailItem label="Email restaurant" value={restaurant.sender_email} />
                  </div>
                  <div className="actions">
                    <button
                      type="button"
                      className="button"
                      disabled={updatingRestaurantId === restaurant.id}
                      onClick={() => void restoreRestaurant(restaurant)}
                    >
                      Restaurer
                    </button>
                    <Link href={`/restaurants/${restaurant.id}`} className="secondary-button">
                      Modifier
                    </Link>
                  </div>
                </article>
              ))}
          </div>
        </details>
      ) : null}
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
