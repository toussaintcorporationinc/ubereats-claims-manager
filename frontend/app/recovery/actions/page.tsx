"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import RecoveryActionCard from "@/components/RecoveryActionCard";
import ResponsiveDataList from "@/components/ResponsiveDataList";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type RecoveryAction,
  type RecoveryFilters,
  type Restaurant,
} from "@/lib/api";

type FilterState = {
  restaurant_id: string;
  date_from: string;
  date_to: string;
};

const initialFilters: FilterState = { restaurant_id: "", date_from: "", date_to: "" };

export default function RecoveryActionsPage() {
  const [actions, setActions] = useState<RecoveryAction[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const queryFilters = useMemo(() => toRecoveryFilters(filters), [filters]);

  const loadData = useCallback(async () => {
    const [actionData, restaurantData] = await Promise.all([
      api.getRecoveryActions({ ...queryFilters, limit: 200 }),
      api.getRestaurants(),
    ]);
    setActions(actionData.actions);
    setRestaurants(restaurantData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  if (loading) {
    return <LoadingState label="Chargement actions recuperation" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Recuperation</p>
          <h1>Actions a traiter</h1>
          <p>Aucun email n'est envoye automatiquement depuis cette file.</p>
        </div>
        <div className="actions">
          <Link href="/recovery" className="secondary-button">
            Cockpit
          </Link>
          <Link href="/recovery/cases" className="secondary-button">
            Cases
          </Link>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select
              id="restaurant_id"
              value={filters.restaurant_id}
              onChange={(event) => setFilters((current) => ({ ...current, restaurant_id: event.target.value }))}
            >
              <option value="">Tous accessibles</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="date_from">Depuis</label>
            <input
              id="date_from"
              type="date"
              value={filters.date_from}
              onChange={(event) => setFilters((current) => ({ ...current, date_from: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="date_to">Jusqu'au</label>
            <input
              id="date_to"
              type="date"
              value={filters.date_to}
              onChange={(event) => setFilters((current) => ({ ...current, date_to: event.target.value }))}
            />
          </div>
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={() => void loadData()}>
            Actualiser
          </button>
          <button type="button" className="secondary-button" onClick={() => setFilters(initialFilters)}>
            Reinitialiser
          </button>
        </div>
      </section>

      <ResponsiveDataList
        items={actions}
        empty={<EmptyState title="Aucune action" />}
        renderMobileCard={(action) => <RecoveryActionCard key={`${action.case_type}-${action.case_id}-${action.action_type}`} action={action} />}
        desktop={
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Restaurant</th>
                  <th>Priorite</th>
                  <th>Montant</th>
                  <th>Echeance</th>
                  <th>Type</th>
                  <th>Ouvrir</th>
                </tr>
              </thead>
              <tbody>
                {actions.map((action) => (
                  <tr key={`${action.case_type}-${action.case_id}-${action.action_type}`}>
                    <td>{action.label}</td>
                    <td>{action.restaurant_name}</td>
                    <td>
                      <StatusBadge status={action.priority} />
                    </td>
                    <td>{formatCurrency(action.amount)}</td>
                    <td>{formatDate(action.due_at)}</td>
                    <td>{action.action_type}</td>
                    <td>
                      <Link className="secondary-button" href={action.url}>
                        Ouvrir
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
      />
    </section>
  );
}

function toRecoveryFilters(filters: FilterState): RecoveryFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    date_from: filters.date_from,
    date_to: filters.date_to,
  };
}
