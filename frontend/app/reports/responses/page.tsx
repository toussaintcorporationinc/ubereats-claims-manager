"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type ClaimResponseReviewType,
  type ReportFilters,
  type ReportResponseRow,
  type Restaurant,
} from "@/lib/api";

type ResponsesFilterState = {
  restaurant_id: string;
  result: string;
};

const initialFilters: ResponsesFilterState = {
  restaurant_id: "",
  result: "",
};

const reviewTypes: ClaimResponseReviewType[] = [
  "accepted",
  "payment_to_verify",
  "payment_confirmed",
  "refused",
  "evidence_requested",
  "information_requested",
  "followup_needed",
  "ignored",
  "manual_review",
];

export default function ReportResponsesPage() {
  const [responses, setResponses] = useState<ReportResponseRow[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<ResponsesFilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const queryFilters = useMemo(() => ({ ...toReportFilters(filters), limit: 200 }), [filters]);

  const loadData = useCallback(async () => {
    const [responsesData, restaurantsData] = await Promise.all([
      api.getReportResponses(queryFilters),
      api.getRestaurants(),
    ]);
    setResponses(responsesData.responses);
    setRestaurants(restaurantsData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleDownload() {
    setDownloading(true);
    setActionError(null);
    try {
      const blob = await api.downloadReport("/v1/reports/export/responses.csv", toReportFilters(filters));
      saveBlob(blob, "ubereats_claims_responses.csv");
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement du rapport reponses" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Rapports</p>
          <h1>Reponses traitees</h1>
        </div>
        <div className="actions">
          <Link href="/reports" className="secondary-button">
            Retour rapports
          </Link>
          <button type="button" className="secondary-button" disabled={downloading} onClick={handleDownload}>
            Export CSV
          </button>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="restaurant_id">Restaurant</label>
            <select
              id="restaurant_id"
              value={filters.restaurant_id}
              onChange={(event) => setFilters((current) => ({ ...current, restaurant_id: event.target.value }))}
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
            <label htmlFor="result">Resultat dossier</label>
            <select
              id="result"
              value={filters.result}
              onChange={(event) => setFilters((current) => ({ ...current, result: event.target.value }))}
            >
              <option value="">Tous</option>
              {reviewTypes.map((reviewType) => (
                <option key={reviewType} value={reviewType}>
                  {reviewType}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={() => void loadData()}>
            Appliquer
          </button>
          <button type="button" className="secondary-button" onClick={() => setFilters(initialFilters)}>
            Reinitialiser
          </button>
        </div>
      </section>

      {responses.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Commande</th>
                <th>Type</th>
                <th>Ancien statut</th>
                <th>Nouveau statut</th>
                <th>Recupere</th>
                <th>Refus</th>
                <th>Date traitement</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {responses.map((response) => (
                <tr key={response.review_id}>
                  <td>{response.restaurant_name}</td>
                  <td>{response.uber_order_number}</td>
                  <td>
                    <StatusBadge status={response.review_type} />
                  </td>
                  <td>
                    <StatusBadge status={response.previous_order_status} />
                  </td>
                  <td>
                    <StatusBadge status={response.new_order_status} />
                  </td>
                  <td>{formatCurrency(response.recovered_amount)}</td>
                  <td>{response.refusal_reason ?? "-"}</td>
                  <td>{formatDate(response.created_at)}</td>
                  <td>
                    <Link href={`/orders/${response.order_id}`} className="secondary-button">
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune reponse traitee dans ce rapport" />
      )}
    </section>
  );
}

function toReportFilters(filters: ResponsesFilterState): ReportFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    result: filters.result,
  };
}

function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}
