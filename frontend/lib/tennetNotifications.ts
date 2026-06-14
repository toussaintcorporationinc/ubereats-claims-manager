import type { WorkspaceMachineRunResponse } from "./api";

const FINISH_NOTIFICATION_STORAGE_KEY = "tennet:finish-notification-enabled";

export async function prepareFinishNotification(): Promise<void> {
  if (!canUseNotifications()) {
    return;
  }
  if (Notification.permission === "granted") {
    window.localStorage.setItem(FINISH_NOTIFICATION_STORAGE_KEY, "true");
    return;
  }
  if (Notification.permission === "default") {
    const permission = await Notification.requestPermission();
    if (permission === "granted") {
      window.localStorage.setItem(FINISH_NOTIFICATION_STORAGE_KEY, "true");
    }
  }
}

export function notifyWorkspaceMachineFinished(result: WorkspaceMachineRunResponse): void {
  if (!canUseNotifications() || Notification.permission !== "granted") {
    return;
  }
  if (window.localStorage.getItem(FINISH_NOTIFICATION_STORAGE_KEY) !== "true") {
    return;
  }
  const sent = sumStages(result, "sent_count");
  const created = sumStages(result, "created_count");
  const failed = sumStages(result, "failed_count");
  const bodyParts = [`${created} dossier(s)/brouillon(s) prepares`, `${sent} email(s) envoyes`];
  if (failed > 0) {
    bodyParts.push(`${failed} action(s) a verifier`);
  }
  new Notification("TENNET a termine son passage", {
    body: bodyParts.join(" · "),
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: `tennet-machine-${result.trigger}`,
  });
}

function canUseNotifications(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

function sumStages(result: WorkspaceMachineRunResponse, key: "created_count" | "sent_count" | "failed_count"): number {
  return result.stages.reduce((total, stage) => total + stage[key], 0);
}
