"use client";

import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import { api, type Restaurant, type UberUnmappedStore } from "@/lib/api";

export default function UberUnmappedStoresPage() {
  const [stores, setStores] = useState<UberUnmappedStore[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [selectedRestaurants, setSelectedRestaurants] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [mappingStoreId, setMappingStoreId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    const [storeData, restaurantData] = await Promise.all([api.getUberUnmappedStores(), api.getRestaurants()]);
    setStores(storeData);
    setRestaurants(restaurantData);
  }, []);

  useEffect(() => {
    loadData().catch(setError).finally(() => setLoading(false));
  }, [loadData]);

  async function handleMap(uberStoreId: string) {
    const restaurantId = Number(selectedRestaurants[uberStoreId]);
    if (!restaurantId) {
      setError(new Error("Selectionnez un restaurant TENNET."));
      return;
    }
    setMappingStoreId(uberStoreId);
    setError(null);
    try {
      await api.mapUberUnmappedStore(uberStoreId, restaurantId);
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setMappingStoreId(null);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement stores non mappes" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Stores non mappes</h1>
        </div>
      </div>
      <ApiError error={error} />
      {stores.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Uber store id</th>
                <th>Nom Uber</th>
                <th>Lignes</th>
                <th>Restaurant TENNET</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {stores.map((store) => (
                <tr key={store.uber_store_id}>
                  <td>{store.uber_store_id}</td>
                  <td>{store.uber_store_name ?? "-"}</td>
                  <td>{store.row_count}</td>
                  <td>
                    <select
                      aria-label={`Restaurant pour ${store.uber_store_id}`}
                      value={selectedRestaurants[store.uber_store_id] ?? ""}
                      onChange={(event) => setSelectedRestaurants((current) => ({ ...current, [store.uber_store_id]: event.target.value }))}
                    >
                      <option value="">Selectionner</option>
                      {restaurants.map((restaurant) => (
                        <option key={restaurant.id} value={restaurant.id}>{restaurant.name}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button"
                      onClick={() => handleMap(store.uber_store_id)}
                      disabled={mappingStoreId === store.uber_store_id}
                    >
                      Mapper
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucun store non mappe" />
      )}
    </section>
  );
}
