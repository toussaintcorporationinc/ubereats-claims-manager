"use client";

import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, type Restaurant, type UberStoreMapping } from "@/lib/api";

export default function UberStoresPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [mappings, setMappings] = useState<UberStoreMapping[]>([]);
  const [restaurantId, setRestaurantId] = useState("");
  const [uberStoreId, setUberStoreId] = useState("");
  const [uberStoreName, setUberStoreName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  async function loadData() {
    const [restaurantData, mappingData] = await Promise.all([api.getRestaurants(), api.getUberStoreMappings()]);
    setRestaurants(restaurantData);
    setMappings(mappingData);
  }

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createUberStoreMapping({
        restaurant_id: Number(restaurantId),
        uber_store_id: uberStoreId,
        uber_store_name: uberStoreName,
        active: true,
      });
      setUberStoreId("");
      setUberStoreName("");
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement mappings Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Mappings stores</h1>
        </div>
      </div>

      <ApiError error={error} />

      <form className="tool-panel form-grid" onSubmit={handleSubmit}>
        <div className="field">
          <label htmlFor="restaurant_id">Restaurant TENNET</label>
          <select id="restaurant_id" value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)} required>
            <option value="">Selectionner</option>
            {restaurants.map((restaurant) => (
              <option key={restaurant.id} value={restaurant.id}>
                {restaurant.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="uber_store_id">Uber store id</label>
          <input id="uber_store_id" value={uberStoreId} onChange={(event) => setUberStoreId(event.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="uber_store_name">Nom store Uber</label>
          <input id="uber_store_name" value={uberStoreName} onChange={(event) => setUberStoreName(event.target.value)} required />
        </div>
        <button type="submit" className="button" disabled={submitting}>
          {submitting ? "Creation" : "Creer mapping"}
        </button>
      </form>

      {mappings.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Uber store id</th>
                <th>Nom Uber</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((mapping) => (
                <tr key={mapping.id}>
                  <td>{restaurants.find((restaurant) => restaurant.id === mapping.restaurant_id)?.name ?? mapping.restaurant_id}</td>
                  <td>{mapping.uber_store_id}</td>
                  <td>{mapping.uber_store_name}</td>
                  <td>
                    <StatusBadge status={mapping.active ? "active" : "inactive"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun mapping Uber store" />
      )}
    </section>
  );
}
