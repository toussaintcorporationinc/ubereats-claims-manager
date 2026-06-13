"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type RecoveryCase,
  type RecoveryCaseType,
  type RecoveryFilters,
  type RecoveryLossCategory,
  type RecoveryStage,
  type Restaurant,
} from "@/lib/api";

const caseTypes: Array<RecoveryCaseType | ""> = ["", "claim_order", "reconciliation_result", "customer_refund_dispute"];
const stages: Array<RecoveryStage | ""> = [
  "",
  "detected",
  "needs_evidence",
  "evidence_ready",
  "draft_created",
  "gmail_draft_created",
  "sent",
  "response_received",
  "accepted",
  "payment_to_verify",
  "payment_confirmed",
  "refused",
  "ignored",
  "manual_review",
];
const categories: Array<RecoveryLossCategory | ""> = [
  "",
  "cancellation_not_compensated",
  "customer_refund",
  "order_not_received",
  "missing_item",
  "incorrect_item",
  "order_error_adjustment",
  "chargeback",
  "manual_review",
];

type FilterState = {
  restaurant_id: string;
  case_type: RecoveryCaseType | "";
  loss_category: RecoveryLossCategory | "";
  recovery_stage: RecoveryStage | "";
  min_amount: string;
  max_amount: string;
  needs_evidence: string;
};

const initialFilters: FilterState = {
  restaurant_id: "",
  case_type: "",
  loss_category: "",
  recovery_stage: "",
  min_amount: "",
  max_amount: "",
  needs_evidence: "",
};

export default function RecoveryCasesPage() {
  const [cases, setCases] = useState<RecoveryCase[]>([]);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const queryFilters = useMemo(() => toRecoveryFilters(filters), [filters]);

  const loadData = useCallback(async () => {
    const [caseData, restaurantData] = await Promise.all([
      api.getRecoveryCases({ ...queryFilters, limit: 200 }),
      api.getRestaurants(),
    ]);
    setCases(caseData.cases);
    setRestaurants(restaurantData);
  }, [queryFilters]);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function handleExport() {
    setDownloading(true);
    setActionError(null);
    try {
      const blob = await api.downloadRecoveryCasesCsv(queryFilters);
      saveBlob(blob, "tennet_recovery_cases.csv");
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement cases recuperation" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Recuperation</p>
          <h1>Cases recuperables</h1>
        </div>
        <div className="actions">
          <Link href="/recovery" className="secondary-button">
            Cockpit
          </Link>
          <Link href="/recovery/actions" className="secondary-button">
            Actions
          </Link>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      <section className="tool-panel">
        <div className="filters">
          <SelectField label="Restaurant" value={filters.restaurant_id} onChange={(value) => setFilters((current) => ({ ...current, restaurant_id: value }))}>
            <option value="">Tous</option>
            {restaurants.map((restaurant) => (
              <option key={restaurant.id} value={restaurant.id}>
                {restaurant.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Type" value={filters.case_type} onChange={(value) => setFilters((current) => ({ ...current, case_type: value as RecoveryCaseType | "" }))}>
            {caseTypes.map((value) => (
              <option key={value || "all"} value={value}>
                {value || "Tous types"}
              </option>
            ))}
          </SelectField>
          <SelectField label="Categorie" value={filters.loss_category} onChange={(value) => setFilters((current) => ({ ...current, loss_category: value as RecoveryLossCategory | "" }))}>
            {categories.map((value) => (
              <option key={value || "all"} value={value}>
                {value || "Toutes categories"}
              </option>
            ))}
          </SelectField>
          <SelectField label="Etape" value={filters.recovery_stage} onChange={(value) => setFilters((current) => ({ ...current, recovery_stage: value as RecoveryStage | "" }))}>
            {stages.map((value) => (
              <option key={value || "all"} value={value}>
                {value || "Toutes etapes"}
              </option>
            ))}
          </SelectField>
          <div className="field">
            <label htmlFor="min_amount">Montant min</label>
            <input id="min_amount" value={filters.min_amount} onChange={(event) => setFilters((current) => ({ ...current, min_amount: event.target.value }))} />
          </div>
          <div className="field">
            <label htmlFor="needs_evidence">Preuve</label>
            <select id="needs_evidence" value={filters.needs_evidence} onChange={(event) => setFilters((current) => ({ ...current, needs_evidence: event.target.value }))}>
              <option value="">Tous</option>
              <option value="true">Preuve requise</option>
              <option value="false">Preuve non bloquante</option>
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
          <button type="button" className="secondary-button" disabled={downloading} onClick={handleExport}>
            Export CSV
          </button>
        </div>
      </section>

      {cases.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Restaurant</th>
                <th>Type</th>
                <th>Categorie</th>
                <th>Commande</th>
                <th>Montant</th>
                <th>Etape</th>
                <th>Preuves</th>
                <th>Prochaine action</th>
                <th>Date</th>
                <th>Ouvrir</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((item) => (
                <tr key={`${item.case_type}-${item.case_id}`}>
                  <td>{item.restaurant_name}</td>
                  <td>{item.case_type}</td>
                  <td>{item.loss_category}</td>
                  <td>{formatOrderIdentity(item.customer_name, item.uber_order_number)}</td>
                  <td>{formatCurrency(item.claimable_amount || item.detected_amount)}</td>
                  <td>
                    <StatusBadge status={item.recovery_stage} />
                  </td>
                  <td>{item.evidence_status ? <StatusBadge status={item.evidence_status} /> : "-"}</td>
                  <td>{item.next_action ?? "-"}</td>
                  <td>{formatDate(item.created_at)}</td>
                  <td>
                    <Link className="secondary-button" href={item.link_url}>
                      Ouvrir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Aucune case" />
      )}
    </section>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  const id = label.toLowerCase().replaceAll(" ", "_");
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </div>
  );
}

function toRecoveryFilters(filters: FilterState): RecoveryFilters {
  return {
    restaurant_id: filters.restaurant_id ? Number(filters.restaurant_id) : "",
    case_type: filters.case_type,
    loss_category: filters.loss_category,
    recovery_stage: filters.recovery_stage,
    min_amount: filters.min_amount,
    max_amount: filters.max_amount,
    needs_evidence: filters.needs_evidence === "" ? undefined : filters.needs_evidence === "true",
  };
}

function formatOrderIdentity(customerName: string | null | undefined, orderNumber: string | null | undefined): string {
  const order = orderNumber ?? "-";
  return customerName ? `${customerName} - ${order}` : order;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.URL.revokeObjectURL(url);
}
