const SERVICE_WORKER_PATH = "/tennet-sw.js";
const PAYMENT_NOTIFICATION_STORAGE_KEY = "tennet:payment-notification-enabled";
const PAYMENT_SUCCESS_SOUND_PATH = "/sounds/success.wav";

export type PaymentRecoveredNotification = {
  recoveredAmount: string;
  totalRecoveredAmount: string;
};

export async function preparePaymentSuccessNotification(): Promise<void> {
  if (!canUseNotifications()) {
    return;
  }

  try {
    if (Notification.permission === "granted") {
      window.localStorage.setItem(PAYMENT_NOTIFICATION_STORAGE_KEY, "true");
      await ensureServiceWorkerRegistration();
      return;
    }

    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission === "granted") {
        window.localStorage.setItem(PAYMENT_NOTIFICATION_STORAGE_KEY, "true");
        await ensureServiceWorkerRegistration();
      }
    }
  } catch {
    // Notification setup must never block TENNET.
  }
}

export function notifyPaymentRecovered(payload: PaymentRecoveredNotification): void {
  window.setTimeout(() => {
    void playPaymentSuccessSound();
    void showPaymentRecoveredNotification(payload).catch(() => {
      // Notifications are optional. Payment tracking must never fail because of them.
    });
  }, 0);
}

async function playPaymentSuccessSound(): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }
  try {
    const audio = new Audio(PAYMENT_SUCCESS_SOUND_PATH);
    audio.volume = 0.9;
    await audio.play();
  } catch {
    // Browsers may block sound until the user interacts with the app.
  }
}

async function showPaymentRecoveredNotification(payload: PaymentRecoveredNotification): Promise<void> {
  if (!canUseNotifications() || Notification.permission !== "granted") {
    return;
  }
  if (window.localStorage.getItem(PAYMENT_NOTIFICATION_STORAGE_KEY) !== "true") {
    return;
  }

  const options: NotificationOptions = {
    body: `TENNET a obtenu un remboursement de ${payload.recoveredAmount}. Total confirme : ${payload.totalRecoveredAmount}.`,
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    tag: `tennet-payment-${Date.now()}`,
  };

  try {
    const registration = await ensureServiceWorkerRegistration();
    if (!registration || typeof registration.showNotification !== "function") {
      return;
    }
    await registration.showNotification("Paiement obtenu par TENNET", options);
  } catch {
    // Notifications are optional. Payment tracking must never fail because of them.
  }
}

function canUseNotifications(): boolean {
  return (
    typeof window !== "undefined" &&
    "Notification" in window &&
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    window.isSecureContext
  );
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
