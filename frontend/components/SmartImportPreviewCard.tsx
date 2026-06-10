"use client";

import StatusBadge from "@/components/StatusBadge";
import type { SmartImportFilePreview } from "@/lib/api";

type Props = {
  file: SmartImportFilePreview;
};

export default function SmartImportPreviewCard({ file }: Props) {
  const confidence = Number(file.confidence ?? 0);

  return (
    <div>
      <div className="card-row">
        <div>
          <h3>{file.original_filename}</h3>
          <p className="muted">{labelForAction(file.recommended_action)}</p>
        </div>
        <StatusBadge status={file.detected_category} />
      </div>
      <div className="detail-grid detail-grid--compact">
        <div className="detail-item">
          <span>Type</span>
          <strong>{file.detected_report_type ? labelForReport(file.detected_report_type) : file.detected_evidence_type ?? "Document"}</strong>
        </div>
        <div className="detail-item">
          <span>Confiance</span>
          <strong>{Math.round(confidence * 100)} %</strong>
        </div>
        <div className="detail-item">
          <span>Header</span>
          <strong>{file.header_row_number ? `Ligne ${file.header_row_number}` : "Non applicable"}</strong>
        </div>
      </div>
      {file.detected_restaurant_name ? <p className="muted">Restaurant probable : {file.detected_restaurant_name}</p> : null}
      {file.detected_date_from || file.detected_date_to ? (
        <p className="muted">
          Periode : {file.detected_date_from ?? "?"} - {file.detected_date_to ?? "?"}
        </p>
      ) : null}
      {file.detected_columns.length > 0 ? (
        <div className="chip-list">
          {file.detected_columns.slice(0, 8).map((column) => (
            <span key={column} className="chip">
              {column}
            </span>
          ))}
        </div>
      ) : null}
      {file.warnings.length > 0 ? <p className="muted">A verifier : {file.warnings.join(", ")}</p> : null}
    </div>
  );
}

function labelForAction(action: string): string {
  const labels: Record<string, string> = {
    import_uber_reporting: "Importer comme rapport Uber",
    import_evidence_bulk: "Importer comme preuves",
    manual_review: "A verifier",
    ignore: "Ignorer",
  };
  return labels[action] ?? action;
}

function labelForReport(reportType: string): string {
  const labels: Record<string, string> = {
    orders_report: "Commandes Uber",
    payments_report: "Paiements Uber",
    adjustments_report: "Ajustements Uber",
    combined_report: "Rapport Uber detecte",
  };
  return labels[reportType] ?? reportType;
}
