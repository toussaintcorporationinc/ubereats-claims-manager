"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { api, type Restaurant } from "@/lib/api";

export default function RestaurantsPage() {
  const { user } = useAuth();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getRestaurants()
      .then(setRestaurants)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Raison sociale</th>
                <th>Adresse</th>
                <th>Email expediteur</th>
                <th>Uber merchant</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {restaurants.map((restaurant) => (
                <tr key={restaurant.id}>
                  <td>{restaurant.name}</td>
                  <td>{restaurant.legal_name ?? "-"}</td>
                  <td>{restaurant.address ?? "-"}</td>
                  <td>{restaurant.sender_email}</td>
                  <td>{restaurant.uber_merchant_id ?? "-"}</td>
                  <td>
                    <StatusBadge status={restaurant.active ? "active" : "inactive"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun restaurant" />
      )}
    </section>
  );
}
