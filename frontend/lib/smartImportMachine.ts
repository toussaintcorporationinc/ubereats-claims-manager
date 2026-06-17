import type { SmartImportFileDecision, SmartImportFilePreview, WorkspaceMachineTrigger } from "@/lib/api";

export function buildMachineSmartImportDecisions(
  files: SmartImportFilePreview[],
  trigger: WorkspaceMachineTrigger,
): SmartImportFileDecision[] {
  return files.map((file) => ({
    file_id: file.id,
    action: actionForMachine(file, trigger),
    report_type: file.detected_report_type ?? "combined_report",
    restaurant_id: null,
  }));
}

function actionForMachine(file: SmartImportFilePreview, trigger: WorkspaceMachineTrigger): SmartImportFileDecision["action"] {
  if (file.recommended_action === "ignore") {
    return "ignore";
  }
  if (trigger === "refunds" || trigger === "cancellations") {
    return "import_evidence_bulk";
  }
  if (file.recommended_action === "manual_review" && shouldForceEvidenceProcessing(file, trigger)) {
    return "import_evidence_bulk";
  }
  return file.recommended_action;
}

function shouldForceEvidenceProcessing(file: SmartImportFilePreview, trigger: WorkspaceMachineTrigger): boolean {
  if (trigger === "refunds" || trigger === "cancellations") {
    return true;
  }
  return file.detected_category === "evidence" || file.detected_category === "zip" || file.detected_category === "unknown";
}
