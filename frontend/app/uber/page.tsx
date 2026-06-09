"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { api, type UberStatus } from "@/lib/api";

export default function UberPage() {
  const [status, setStatus] = useState<UberStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getUberStatus()
      .then(setStatus)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState label="Chargement integration Uber" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Connecteur officiel</h1>
        </div>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Strategie d'acces</h2>
          {status ? <StatusBadge status={status.status} /> : null}
        </div>
        <div className="detail-grid">
          <DetailItem label="API officielle" value="Preparation uniquement" />
          <DetailItem label="Approbation Uber" value="Requise avant appel API reel" />
          <DetailItem label="Fallback V1" value="Import rapports Uber Eats Manager CSV/XLSX" />
          <DetailItem label="Scraping tablette" value="Interdit" />
        </div>
      </section>

      <div className="action-row">
        <Link className="button" href="/uber/stores">
          Mapper les stores Uber
        </Link>
        <Link className="secondary-button" href="/uber/reconciliation">
          Reconciliation
        </Link>
      </div>
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
