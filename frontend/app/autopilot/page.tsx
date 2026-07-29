"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import {
  api,
  formatDateTime,
  type AutopilotAction,
  type AutopilotMode,
  type AutopilotRunDetail,
  type AutopilotStatusResponse,
  type Restaurant,
} from "@/lib/api";

type RunMode = Exclude<AutopilotMode, "emergency_stop">;

const modes: RunMode[] = ["all", "initial_claims", "followups", "appeals"];

export default function AutopilotPage() {
  const [status, setStatus] = useState<AutopilotStatusResponse | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [mode, setMode] = useState<RunMode>("all");
  const [restaurantId, setRestaurantId] = useState("");
  const [lastRun, setLastRun] = useState<AutopilotRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadData = useCallback(async () => {
    const [statusData, restaurantData] = await Promise.all([api.getAutopilotStatus(), api.getRestaurants()]);
    setStatus(statusData);
    setRestaurants(restaurantData);
  }, []);

  useEffect(() => {
    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [loadData]);

  async function execute(dryRun: boolean) {
    setRunning(true);
    setError(null);
    try {
      const payload = {
        mode,
        restaurant_id: restaurantId ? Number(restaurantId) : null,
      };
      const result = dryRun ? await api.dryRunAutopilot(payload) : await api.runAutopilot(payload);
      setLastRun(result);
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setRunning(false);
    }
  }

  async function stop() {
    setRunning(true);
    setError(null);
    try {
      await api.stopAutopilot();
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setRunning(false);
    }
  }

  async function resume() {
    setRunning(true);
    setError(null);
    try {
      await api.resumeAutopilot();
      await loadData();
    } catch (apiError) {
      setError(apiError);
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement AutoPilot" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">AutoPilot</p>
          <h1>Envois controles Gmail</h1>
          <p>TENNET peut envoyer automatiquement seulement si les règles de sécurité sont remplies.</p>
        </div>
        <div className="actions">
          <Link href="/autopilot/runs" className="secondary-button">
            Runs
          </Link>
          {status?.emergency_stopped ? (
            <button type="button" className="button" disabled={running} onClick={() => void resume()}>
              Reprendre sous limites Gmail
            </button>
          ) : (
            <button type="button" className="danger-button" disabled={running} onClick={() => void stop()}>
              Arret urgence
            </button>
          )}
        </div>
      </div>

      <ApiError error={error} />

      {status ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Etat</h2>
            <StatusBadge status={status.settings.enabled && !status.emergency_stopped ? "active" : "inactive"} />
          </div>
          <div className="detail-grid">
            <DetailItem label="AutoPilot" value={status.settings.enabled ? "active" : "desactive"} />
            <DetailItem label="Gmail" value={status.gmail_connected ? status.gmail_email_address ?? "connecte" : "non connecte"} />
            <DetailItem label="Provider email" value={status.gmail_provider_enabled ? "active" : "desactive"} />
            <DetailItem label="Restant aujourd'hui" value={String(status.remaining_today_count)} />
            <DetailItem label="Limite globale" value={String(status.settings.daily_send_limit)} />
            <DetailItem label="Limite restaurant" value={String(status.settings.per_restaurant_daily_limit)} />
            <DetailItem label="Cooldown" value={`${status.settings.cooldown_hours} h`} />
            <DetailItem label="Arret urgence" value={status.emergency_stopped ? "actif" : "non"} />
          </div>
        </section>
      ) : null}

      <section className="tool-panel">
        <div className="filters">
          <div className="field">
            <label htmlFor="autopilot_mode">Mode</label>
            <select id="autopilot_mode" value={mode} onChange={(event) => setMode(event.target.value as RunMode)}>
              {modes.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="autopilot_restaurant">Restaurant</label>
            <select id="autopilot_restaurant" value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)}>
              <option value="">Tous accessibles</option>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>
                  {restaurant.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="actions">
          <button type="button" className="secondary-button" disabled={running} onClick={() => void execute(true)}>
            Dry-run
          </button>
          <button type="button" className="button" disabled={running} onClick={() => void execute(false)}>
            Lancer AutoPilot
          </button>
        </div>
      </section>

      {lastRun ? (
        <section className="tool-panel">
          <div className="section-heading">
            <h2>Dernier resultat</h2>
            <StatusBadge status={lastRun.run.status} />
          </div>
          <div className="detail-grid">
            <DetailItem label="Run" value={`#${lastRun.run.id}`} />
            <DetailItem label="Mode" value={lastRun.run.mode} />
            <DetailItem label="Candidats" value={String(lastRun.run.total_candidates)} />
            <DetailItem label="Envoyes" value={String(lastRun.run.sent_count)} />
            <DetailItem label="Ignores" value={String(lastRun.run.skipped_count)} />
            <DetailItem label="Echecs" value={String(lastRun.run.failed_count)} />
          </div>
          <ActionsTable actions={lastRun.actions} />
        </section>
      ) : (
        <EmptyState title="Aucun dry-run lance" />
      )}
    </section>
  );
}

function ActionsTable({ actions }: { actions: AutopilotAction[] }) {
  if (actions.length === 0) {
    return <EmptyState title="Aucune action candidate" />;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Action</th>
            <th>Case</th>
            <th>Restaurant</th>
            <th>Statut</th>
            <th>Raison</th>
            <th>Envoi</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.id}>
              <td>{action.action_type}</td>
              <td>
                {action.case_type} #{action.case_id}
              </td>
              <td>{action.restaurant_id}</td>
              <td>
                <StatusBadge status={action.status} />
              </td>
              <td>{action.skipped_reason ?? action.reason}</td>
              <td>{formatDateTime(action.sent_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
