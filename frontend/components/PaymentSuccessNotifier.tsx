"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, formatCurrency, type MoneyValue } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { notifyPaymentRecovered, preparePaymentSuccessNotification } from "@/lib/tennetNotifications";

const POLL_INTERVAL_MS = 60_000;
const STORAGE_PREFIX = "tennet:payment-success:last-recovered-cents";

type PaymentNotice = {
  amount: string;
  total: string;
};

export default function PaymentSuccessNotifier() {
  const { user, loading } = useAuth();
  const [notice, setNotice] = useState<PaymentNotice | null>(null);
  const checkingRef = useRef(false);
  const noticeTimerRef = useRef<number | null>(null);
  const enabled = !loading && user !== null && user.role !== "staff";
  const storageKey = useMemo(() => (user ? `${STORAGE_PREFIX}:${user.id}` : STORAGE_PREFIX), [user]);

  const checkRecoveredAmount = useCallback(async () => {
    if (!enabled || checkingRef.current) {
      return;
    }

    checkingRef.current = true;
    try {
      const summary = await api.getDashboardSummary();
      const currentCents = moneyToCents(summary.total_recovered_amount);
      const storedCents = readStoredCents(storageKey);

      if (storedCents === null) {
        writeStoredCents(storageKey, currentCents);
        return;
      }

      if (currentCents > storedCents) {
        const deltaCents = currentCents - storedCents;
        writeStoredCents(storageKey, currentCents);
        const payload = {
          recoveredAmount: formatCents(deltaCents),
          totalRecoveredAmount: formatCents(currentCents),
        };
        notifyPaymentRecovered(payload);
        showInAppNotice(payload);
        return;
      }

      if (currentCents < storedCents) {
        writeStoredCents(storageKey, currentCents);
      }
    } catch {
      // Payment notifications must never break the app.
    } finally {
      checkingRef.current = false;
    }
  }, [enabled, storageKey]);

  function showInAppNotice(payload: { recoveredAmount: string; totalRecoveredAmount: string }) {
    setNotice({ amount: payload.recoveredAmount, total: payload.totalRecoveredAmount });
    if (noticeTimerRef.current !== null) {
      window.clearTimeout(noticeTimerRef.current);
    }
    noticeTimerRef.current = window.setTimeout(() => setNotice(null), 9_000);
  }

  useEffect(() => {
    if (!enabled) {
      return;
    }

    function prepareNotifications() {
      void preparePaymentSuccessNotification();
      window.removeEventListener("pointerdown", prepareNotifications, true);
      window.removeEventListener("keydown", prepareNotifications, true);
    }

    window.addEventListener("pointerdown", prepareNotifications, true);
    window.addEventListener("keydown", prepareNotifications, true);

    return () => {
      window.removeEventListener("pointerdown", prepareNotifications, true);
      window.removeEventListener("keydown", prepareNotifications, true);
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    void checkRecoveredAmount();
    const intervalId = window.setInterval(() => void checkRecoveredAmount(), POLL_INTERVAL_MS);

    function handleFocus() {
      void checkRecoveredAmount();
    }

    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        void checkRecoveredAmount();
      }
    }

    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      if (noticeTimerRef.current !== null) {
        window.clearTimeout(noticeTimerRef.current);
      }
    };
  }, [checkRecoveredAmount, enabled]);

  if (!notice) {
    return null;
  }

  return (
    <div className="payment-success-toast" role="status" aria-live="polite">
      <span>Paiement obtenu</span>
      <strong>TENNET a obtenu un remboursement de {notice.amount}</strong>
      <small>Total confirme : {notice.total}</small>
    </div>
  );
}

function readStoredCents(key: string): number | null {
  const raw = window.localStorage.getItem(key);
  if (raw === null) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function writeStoredCents(key: string, value: number): void {
  window.localStorage.setItem(key, String(value));
}

function moneyToCents(value: MoneyValue): number {
  if (value === null) {
    return 0;
  }
  const numeric = typeof value === "number" ? value : Number(String(value).replace(",", "."));
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return Math.round(numeric * 100);
}

function formatCents(cents: number): string {
  return formatCurrency((cents / 100).toFixed(2));
}
