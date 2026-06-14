"use client";

import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, type Restaurant, type UberStoreMapping, type UberUnmappedStore } from "@/lib/api";

export default function UberStoresPage() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [mappings, setMappings] = useState<UberStoreMapping[]>([]);
  const [unmappedStores, setUnmappedStores] = useState<UberUnmappedStore[]>([]);
  const [detectedRestaurantId, setDetectedRestaurantId] = useState("");
  const [selectedUberStoreId, setSelectedUberStoreId] = useState("");
  const [manualRestaurantId, setManualRestaurantId] = useState("");
  const [manualUberStoreId, setManualUberStoreId] = useState("");
  const [manualUberStoreName, setManualUberStoreName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  async function loadData() {
    const [restaurantData, mappingData, unmappedData] = await Promise.all([
      api.getRestaurants(),
      api.getUberStoreMappings(),
      api.getUberUnmappedStores(),
    ]);
    setRestaurants(restaurantData);
    setMappings(mappingData);
    setUnmappedStores(unmappedData);
  }

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleDetectedSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.mapUberUnmappedStore(selectedUberStoreId, Number(detectedRestaurantId));
      setSelectedUberStoreId("");
      setDetectedRestaurantId("");
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleManualSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.createUberStoreMapping({
        restaurant_id: Number(manualRestaurantId),
        uber_store_id: manualUberStoreId.trim() || null,
        uber_store_name: manualUberStoreName,
        active: true,
      });
      setManualRestaurantId("");
      setManualUberStoreId("");
      setManualUberStoreName("");
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
          <h1>Restaurants Uber</h1>
          <p className="muted">Relie un nom Uber au bon restaurant TENNET. L'identifiant technique est optionnel.</p>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Stores detectes a mapper</h2>
            <p className="muted">TENNET les trouve dans les imports Uber. Tu relies seulement le bon restaurant.</p>
          </div>
        </div>

        {unmappedStores.length > 0 ? (
          <form className="form-grid" onSubmit={handleDetectedSubmit}>
            <div className="field">
              <label htmlFor="detected_uber_store">Store Uber detecte</label>
              <select
                id="detected_uber_store"
                value={selectedUberStoreId}
                onChange={(event) => {
                  const storeId = event.target.value;
                  const selectedStore = unmappedStores.find((store) => store.uber_store_id === storeId);
                  setSelectedUberStoreId(storeId);
                  setDetectedRestaurantId(selectedStore?.suggested_restaurant_matches[0]?.id.toString() ?? "");
                }}
                required
              >
                <option value="">Selectionner un store detecte</option>
                {unmappedStores.map((store) => (
                  <option key={store.uber_store_id} value={store.uber_store_id}>
                    {store.uber_store_name ?? "Store Uber"} - {store.row_count} ligne(s)
                  </option>
                ))}
              </select>
              {selectedUberStoreId ? <small className="muted">ID technique conserve par TENNET : {selectedUberStoreId}</small> : null}
            </div>

            <div className="field">
              <label htmlFor="detected_restaurant_id">Restaurant TENNET</label>
              <select
                id="detected_restaurant_id"
                value={detectedRestaurantId}
                onChange={(event) => setDetectedRestaurantId(event.target.value)}
                required
              >
                <option value="">Choisir le restaurant</option>
                {restaurants.map((restaurant) => (
                  <option key={restaurant.id} value={restaurant.id}>
                    {restaurant.name}
                  </option>
                ))}
              </select>
            </div>

            <button type="submit" className="button" disabled={submitting}>
              {submitting ? "Mapping" : "Mapper ce store"}
            </button>
          </form>
        ) : (
          <EmptyState title="Aucun store Uber a mapper" description="Quand un import Uber contient un store inconnu, il apparaitra ici." />
        )}
      </section>

      <details className="simple-details">
        <summary>Ajouter un restaurant Uber manuellement</summary>
        <form className="tool-panel form-grid" onSubmit={handleManualSubmit}>
          <div className="field">
            <label htmlFor="manual_restaurant_id">Restaurant TENNET</label>
            <select
              id="manual_restaurant_id"
              value={manualRestaurantId}
              onChange={(event) => setManualRestaurantId(event.target.value)}
              required
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
            <label htmlFor="manual_uber_store_name">Nom vu dans Uber</label>
            <input
              id="manual_uber_store_name"
              value={manualUberStoreName}
              onChange={(event) => setManualUberStoreName(event.target.value)}
              placeholder="Ex : Krousty Bat"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="manual_uber_store_id">ID Uber si tu l'as</label>
            <input
              id="manual_uber_store_id"
              value={manualUberStoreId}
              onChange={(event) => setManualUberStoreId(event.target.value)}
              placeholder="Optionnel : TENNET le genere sinon"
            />
            <small className="muted">Tu peux laisser vide. TENNET utilisera un identifiant interne stable.</small>
          </div>
          <button type="submit" className="secondary-button" disabled={submitting}>
            {submitting ? "Creation" : "Relier ce restaurant Uber"}
          </button>
        </form>
      </details>

      {mappings.length > 0 ? (
        <div className="premium-card-grid">
          {mappings.map((mapping) => (
            <article key={mapping.id} className="premium-card">
              <div className="section-heading">
                <div>
                  <h3>{restaurants.find((restaurant) => restaurant.id === mapping.restaurant_id)?.name ?? mapping.restaurant_id}</h3>
                  <p className="muted">{mapping.uber_store_name}</p>
                </div>
                <StatusBadge status={mapping.active ? "active" : "inactive"} />
              </div>
              <p className="muted">Store Uber : {mapping.uber_store_id}</p>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title="Aucun mapping Uber store" />
      )}
    </section>
  );
}
