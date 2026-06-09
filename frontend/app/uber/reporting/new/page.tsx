"use client";

import { ChangeEvent, useState } from "react";
import { useRouter } from "next/navigation";
import ApiError from "@/components/ApiError";
import { api, type UberReportingReportType } from "@/lib/api";

const reportTypes: UberReportingReportType[] = ["orders_report", "payments_report", "adjustments_report", "combined_report"];

export default function NewUberReportingImportPage() {
  const router = useRouter();
  const [reportType, setReportType] = useState<UberReportingReportType>("orders_report");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  async function handlePreview() {
    if (!file) {
      setError(new Error("Selectionnez un fichier CSV ou XLSX."));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const preview = await api.previewUberReportingImport(file, reportType);
      router.push(`/uber/reporting/${preview.batch_id}`);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Uber Eats</p>
          <h1>Analyser un rapport</h1>
        </div>
      </div>
      <ApiError error={error} />
      <section className="tool-panel form-grid">
        <p>Importez un export officiel Uber Eats Manager ou Uber Reporting. Aucun mot de passe Uber n'est demande.</p>
        <div className="field">
          <label htmlFor="report_type">Type de rapport TENNET</label>
          <select id="report_type" value={reportType} onChange={(event) => setReportType(event.target.value as UberReportingReportType)}>
            {reportTypes.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="file">Fichier CSV/XLSX</label>
          <input id="file" type="file" accept=".csv,.xlsx" onChange={(event: ChangeEvent<HTMLInputElement>) => setFile(event.target.files?.[0] ?? null)} />
        </div>
        <button type="button" className="button" onClick={handlePreview} disabled={loading}>
          {loading ? "Analyse" : "Analyser"}
        </button>
      </section>
    </section>
  );
}
