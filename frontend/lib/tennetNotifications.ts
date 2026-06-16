import type { WorkspaceMachineRunResponse } from "./api";

const FINISH_NOTIFICATION_STORAGE_KEY = "tennet:finish-notification-enabled";
const SERVICE_WORKER_PATH = "/tennet-sw.js";

export async function prepareFinishNotification(): Promise<void> {
  if (!canUseNotifications()) {
    return;
  }

  try {
    if (Notification.permission === "granted") {
      window.localStorage.setItem(FINISH_NOTIFICATION_STORAGE_KEY, "true");
      await ensureServiceWorkerRegistration();
      return;
    }

    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission === "granted") {
        window.localStorage.setItem(FINISH_NOTIFICATION_STORAGE_KEY, "true");
        await ensureServiceWorkerRegistration();
      }
    }
  } catch {
    // Notification setup must never block the recovery machine.
  }
}

export function notifyWorkspaceMachineFinished(result: WorkspaceMachineRunResponse): void {
  void showFinishNotification(result);
}

async function showFinishNotification(result: WorkspaceMachineRunResponse): Promise<void> {
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

  const options: NotificationOptions = {
    body: bodyParts.join(" - "),
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: `tennet-machine-${result.trigger}`,
  };

  try {
    const registration = await ensureServiceWorkerRegistration();
    await registration?.showNotification("TENNET a termine son passage", options);
  } catch {
    // Notifications are optional. The recovery machine must never fail because of them.
  }
}

function canUseNotifications(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

async function ensureServiceWorkerRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return null;
  }

  const existing = await navigator.serviceWorker.getRegistration(SERVICE_WORKER_PATH);
  if (existing) {
    return existing;
  }

  return navigator.serviceWorker.register(SERVICE_WORKER_PATH, { scope: "/" });
}

function sumStages(result: WorkspaceMachineRunResponse, key: "created_count" | "sent_count" | "failed_count"): number {
  return result.stages.reduce((total, stage) => total + stage[key], 0);
}
