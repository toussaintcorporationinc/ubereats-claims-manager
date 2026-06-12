"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import MobileActionBar from "@/components/MobileActionBar";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatCurrency,
  formatDate,
  type EvidencePrintTicketResponse,
  type EvidenceRequestPriority,
  type EvidenceRequestTaskSummary,
  type EvidenceType,
  type LiveEvidenceStationResponse,
} from "@/lib/api";

const evidenceLabels: Record<EvidenceType, string> = {
  receipt: "Ticket de caisse",
  cancellation_proof: "Preuve annulation",
  preparation_proof: "Preuve preparation",
  waste_photo: "Photo gaspillage",
  uber_screenshot: "Capture Uber",
  delivery_proof: "Preuve livraison",
  packaging_photo: "Photo emballage",
  sealed_bag_photo: "Photo sac ferme",
  courier_statement: "Message livreur",
  gps_or_route_proof: "Preuve GPS",
  customer_contact_proof: "Contact client",
  order_details_screenshot: "Details commande",
  other: "Autre preuve",
};

const priorityFilters: Array<EvidenceRequestPriority | ""> = ["", "urgent", "high", "normal", "low"];

export default function LiveEvidenceStationPage() {
  const [station, setStation] = useState<LiveEvidenceStationResponse | null>(null);
  const [priority, setPriority] = useState<EvidenceRequestPriority | "">("");
  const [tickets, setTickets] = useState<Record<number, EvidencePrintTicketResponse>>({});
  const [printingTaskId, setPrintingTaskId] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const loadStation = useCallback(async () => {
    const data = await api.getLiveEvidenceStation({ priority, limit: 100 });
    setStation(data);
  }, [priority]);

  useEffect(() => {
    setLoading(true);
    loadStation()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadStation]);

  async function handlePrint(task: EvidenceRequestTaskSummary) {
    setPrintingTaskId(task.id);
    setActionError(null);

    try {
      const ticket = await api.createEvidencePrintTicket(task.id);
      setTickets((current) => ({ ...current, [task.id]: ticket }));
      openPrintTicket(ticket);
      await loadStation();
    } catch (apiError) {
      setActionError(apiError);
    } finally {
      setPrintingTaskId(null);
    }
  }

  function openPrintTicket(ticket: EvidencePrintTicketResponse) {
    const printWindow = window.open("", "_blank", "width=420,height=720");
    if (!printWindow) {
      setActionError(new Error("La fenetre d'impression a ete bloquee. Utilisez le bouton Ouvrir upload."));
      return;
    }
    printWindow.document.open();
    printWindow.document.write(ticket.print_html);
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
  }

  if (loading) {
    return <LoadingState label="Ouverture station preuves terrain" />;
  }

  const tasks = station?.tasks ?? [];
  const recommendedTask = tasks.find((task) => task.id === station?.recommended_task_id) ?? tasks[0] ?? null;

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Terrain</p>
          <h1>Station preuves</h1>
          <p className="muted">
            Imprimez le ticket TENNET, prenez la preuve en photo, puis scannez le QR code pour classer la preuve au bon dossier.
          </p>
        </div>
        <div className="actions">
          <button type="button" className="secondary-button" onClick={() => void loadStation()}>
            Rafraichir
          </button>
          <Link href="/evidence-tasks" className="secondary-button">
            Toutes les preuves
          </Link>
        </div>
      </div>

      <ApiError error={error} />
      <ApiError error={actionError} />

      {station ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>File active</h2>
            <span className="muted">
              Web: impression systeme. App Android: ticket Bluetooth ESC/POS + camera directe. Aucune lecture tablette Uber.
            </span>
          </div>
          <div className="detail-grid detail-grid--compact">
            <StationMetric label="A traiter" value={station.total_active_tasks} />
            <StationMetric label="Urgentes" value={station.urgent_count} />
            <StationMetric label="Haute priorite" value={station.high_priority_count} />
            <StationMetric label="Deja uploadees" value={station.uploaded_count} />
          </div>
          <div className="success-box">
            <strong>Materiel terrain</strong>
            <span>Camera mobile : {station.camera_capture_supported ? "prete" : "non disponible"}</span>
            <span>Web : dialogue systeme / imprimante deja appairee</span>
            <span>
              App Android :{" "}
              {station.native_print_modes.includes("android_bluetooth_escpos")
                ? `Bluetooth ESC/POS pret (${station.native_print_contract_version})`
                : "non disponible"}
            </span>
          </div>
          <div className="filters">
            <div className="field">
              <label htmlFor="priority_filter">Priorite</label>
              <select
                id="priority_filter"
                value={priority}
                onChange={(event) => setPriority(event.target.value as EvidenceRequestPriority | "")}
              >
                {priorityFilters.map((item) => (
                  <option key={item || "all"} value={item}>
                    {item || "Toutes"}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>
      ) : null}

      {recommendedTask ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Prochaine preuve</h2>
            <StatusBadge status={recommendedTask.priority} />
          </div>
          <EvidenceStationCard
            task={recommendedTask}
            ticket={tickets[recommendedTask.id]}
            primary
            printing={printingTaskId === recommendedTask.id}
            onPrint={() => void handlePrint(recommendedTask)}
          />
        </section>
      ) : null}

      <section className="tool-panel">
        <div className="section-heading">
          <h2>Toutes les preuves terrain</h2>
          <span className="muted">Aucune preuve n'est inventee. Aucun email n'est envoye automatiquement.</span>
        </div>
        {tasks.length ? (
          <div className="premium-card-grid">
            {tasks.map((task) => (
              <EvidenceStationCard
                key={task.id}
                task={task}
                ticket={tickets[task.id]}
                printing={printingTaskId === task.id}
                onPrint={() => void handlePrint(task)}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="Aucune preuve terrain a collecter" />
        )}
      </section>

      {station?.safe_capture_rules.length ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Regles terrain</h2>
          </div>
          <ul className="stack-sm">
            {station.safe_capture_rules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {recommendedTask ? (
        <MobileActionBar>
          <button
            type="button"
            className="button"
            disabled={printingTaskId === recommendedTask.id}
            onClick={() => void handlePrint(recommendedTask)}
          >
            {printingTaskId === recommendedTask.id ? "Preparation" : "Imprimer ticket"}
          </button>
          {tickets[recommendedTask.id] ? (
            <a className="secondary-button" href={tickets[recommendedTask.id].upload_url} target="_blank" rel="noreferrer">
              Ouvrir photo
            </a>
          ) : null}
        </MobileActionBar>
      ) : null}
    </section>
  );
}

function EvidenceStationCard({
  task,
  ticket,
  primary = false,
  printing,
  onPrint,
}: {
  task: EvidenceRequestTaskSummary;
  ticket?: EvidencePrintTicketResponse;
  primary?: boolean;
  printing: boolean;
  onPrint: () => void;
}) {
  return (
    <article className={`premium-card evidence-station-card${primary ? " evidence-station-card--primary" : ""}`}>
      <div className="card-row">
        <div>
          <h3>{evidenceLabels[task.required_evidence_type] ?? task.title}</h3>
          <p className="muted">{task.restaurant_name}</p>
        </div>
        <StatusBadge status={task.status} />
      </div>
      <div className="detail-grid detail-grid--compact">
        <div className="detail-item">
          <span>Commande</span>
          <strong>{task.uber_order_number}</strong>
        </div>
        <div className="detail-item">
          <span>Montant</span>
          <strong>{formatCurrency(task.order_amount, task.currency)}</strong>
        </div>
        <div className="detail-item">
          <span>Echeance</span>
          <strong>{formatDate(task.due_at)}</strong>
        </div>
      </div>
      <p>{task.description || task.reason}</p>
      <div className="card-row card-row--bottom">
        <StatusBadge status={task.priority} />
        <span className="muted">Ticket + photo + QR</span>
      </div>
      <div className="actions">
        <button type="button" className="button" disabled={printing} onClick={onPrint}>
          {printing ? "Preparation" : "Imprimer ticket"}
        </button>
        {ticket ? (
          <a className="secondary-button" href={ticket.upload_url} target="_blank" rel="noreferrer">
            Ouvrir upload photo
          </a>
        ) : null}
        <Link href={`/evidence-tasks/${task.id}`} className="secondary-button">
          Detail
        </Link>
      </div>
    </article>
  );
}

function StationMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="detail-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
