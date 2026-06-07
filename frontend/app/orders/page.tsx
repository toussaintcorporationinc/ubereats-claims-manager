"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, formatCurrency, type ClaimOrder, type Restaurant } from "@/lib/api";

export default function OrdersPage() {
  const [orders, setOrders] = useState<ClaimOrder[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantFilter, setRestaurantFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getOrders(), api.getRestaurants()])
      .then(([ordersData, restaurantsData]) => {
        setOrders(ordersData);
        setRestaurants(restaurantsData);
      })
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  const restaurantById = useMemo(
    () => new Map(restaurants.map((restaurant) => [restaurant.id, restaurant])),
    [restaurants],
  );

  const statuses = useMemo(() => Array.from(new Set(orders.map((order) => order.status))).sort(), [orders]);

  const filteredOrders = orders.filter((order) => {
    const restaurantMatches = restaurantFilter ? String(order.restaurant_id) === restaurantFilter : true;
    const statusMatches = statusFilter ? order.status === statusFilter : true;
    return restaurantMatches && statusMatches;
  });

  if (loading) {
    return <LoadingState label="Chargement des commandes" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Commandes</p>
          <h1>Commandes contestees</h1>
        </div>
        <Link href="/orders/new" className="button">
          Creer commande
        </Link>
      </div>

      <ApiError error={error} />

      <div className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_filter">Restaurant</label>
            <select
              id="restaurant_filter"
              value={restaurantFilter}
              onChange={(event) => setRestaurantFilter(event.target.value)}
            >
              <option value="">Tous</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="status_filter">Statut</label>
            <select id="status_filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">Tous</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {filteredOrders.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Numero Uber</th>
                <th>Client</th>
                <th>Date</th>
                <th>Montant</th>
                <th>Statut</th>
                <th>Relances</th>
                <th>Resultat</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map((order) => (
                <tr key={order.id}>
                  <td>{restaurantById.get(order.restaurant_id)?.name ?? `#${order.restaurant_id}`}</td>
                  <td>{order.uber_order_number}</td>
                  <td>{order.customer_name ?? "-"}</td>
                  <td>{order.order_date ?? "-"}</td>
                  <td>{formatCurrency(order.order_amount, order.currency)}</td>
                  <td>
                    <StatusBadge status={order.status} />
                  </td>
                  <td>{order.retry_count}</td>
                  <td>{order.result ?? "-"}</td>
                  <td>
                    <Link href={`/orders/${order.id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune commande" />
      )}
    </section>
  );
}
