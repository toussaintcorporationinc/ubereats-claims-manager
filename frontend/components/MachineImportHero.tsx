"use client";

import { useState } from "react";
import ApiError from "@/components/ApiError";
import { buildMachineSmartImportDecisions } from "@/lib/smartImportMachine";
import { api, type WorkspaceMachineRunResponse, type WorkspaceMachineTrigger } from "@/lib/api";

const acceptedTypes = ".csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.zip,image/*,application/pdf";

type MachineImportHeroProps = {
  eyebrow: string;
  title: string;
  description: string;
  instruction: string;
  fileButtonLabel: string;
  trigger: Extract<WorkspaceMachineTrigger, "refunds" | "cancellations">;
};

export default function MachineImportHero({
  eyebrow,
  title,
  description,
  instruction,
  fileButtonLabel,
  trigger,
}: MachineImportHeroProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<WorkspaceMachineRunResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const inputId = `machine-files-${trigger}`;

  async function runMachine() {
    if (files.length === 0) {
      return;
    }
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      const preview = await api.previewSmartImport(files);
      const decisions = buildMachineSmartImportDecisions(preview.files, trigger);
      await api.confirmSmartImport(preview.batch_preview_id, decisions);
      const machineResult = await api.runWorkspaceMachine({
        trigger,
        smart_import_batch_id: preview.batch_preview_id,
        sync_gmail: true,
        run_autopilot: true,
      });
      setResult(machineResult);
      setFiles([]);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <div className="machine-hero machine-hero--category">
        <div className="heading-copy">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>

        <div className={`machine-category-orb ${running ? "machine-command--running" : ""}`}>
          <div className="machine-command">
            <div className="machine-ring" aria-hidden="true">
              <span />
            </div>
            <div className="machine-command__content">
              <strong>{running ? "TENNET travaille" : "TENNET pret"}</strong>
              <span>{files.length > 0 ? `${files.length} fichier(s)` : "Import massif"}</span>
            </div>
          </div>
          <p>{instruction}</p>
        </div>

        <div className="machine-hero__actions">
          <label className="button button--hero machine-file-button" htmlFor={inputId}>
            {fileButtonLabel}
          </label>
          <input
            id={inputId}
            className="machine-file-input"
            type="file"
            multiple
            accept={acceptedTypes}
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          <button
            type="button"
            className="button button--hero machine-go-button"
            disabled={running || files.length === 0}
            onClick={() => void runMachine()}
          >
            {running ? "TENNET travaille" : "GO"}
          </button>
          <p className="machine-action-note">
            {files.length > 0
              ? `${files.length} fichier(s) prets. GO lance import, classement, preuves, emails et suivi autorise.`
              : "Importe tout en masse. GO lance ensuite toute la machine automatiquement."}
          </p>
        </div>
      </div>
      <ApiError error={error} />
      {result ? <MachineCategoryResult result={result} /> : null}
    </>
  );
}

function MachineCategoryResult({ result }: { result: WorkspaceMachineRunResponse }) {
  const processed = result.stages.reduce((total, stage) => total + stage.processed_count, 0);
  const created = result.stages.reduce((total, stage) => total + stage.created_count, 0);
  const sent = result.stages.reduce((total, stage) => total + stage.sent_count, 0);
  const blocked = result.stages.reduce((total, stage) => total + stage.skipped_count + stage.failed_count, 0);

  return (
    <section className={`machine-result machine-result--${result.status}`}>
      <div>
        <strong>TENNET a termine le passage</strong>
        <p>Les fichiers exploitables ont ete routes. Les blocages reels restent visibles pour correction.</p>
      </div>
      <div className="simple-pilot-grid">
        <div className="detail-item">
          <span>Traites</span>
          <strong>{processed}</strong>
        </div>
        <div className="detail-item">
          <span>Crees</span>
          <strong>{created}</strong>
        </div>
        <div className="detail-item">
          <span>Envoyes</span>
          <strong>{sent}</strong>
        </div>
        <div className="detail-item">
          <span>A corriger</span>
          <strong>{blocked}</strong>
        </div>
      </div>
    </section>
  );
}
