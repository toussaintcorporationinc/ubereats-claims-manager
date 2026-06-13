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
        api.getRestaurants(),
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

      {restaurants.length > 0 ? (
        <div className="restaurant-card-grid">
          {restaurants.map((restaurant) => {
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
        <EmptyState title="Aucun restaurant" />
      )}
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
