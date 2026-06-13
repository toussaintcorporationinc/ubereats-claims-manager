"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import ApiError from "@/components/ApiError";
import EmptyState from "@/components/EmptyState";
import LoadingState from "@/components/LoadingState";
import StatusBadge from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  api,
  emptyToNull,
  formatDate,
  type EmailAccount,
  type GmailRestaurantMapping,
  type Restaurant,
  type UberStoreMapping,
} from "@/lib/api";

type RestaurantForm = {
  name: string;
  legal_name: string;
  address: string;
  phone_number: string;
  sender_email: string;
  uber_merchant_id: string;
  active: boolean;
  autopilot_enabled: boolean;
};

function restaurantToForm(restaurant: Restaurant): RestaurantForm {
  return {
    name: restaurant.name,
    legal_name: restaurant.legal_name ?? "",
    address: restaurant.address ?? "",
    phone_number: restaurant.phone_number ?? "",
    sender_email: restaurant.sender_email,
    uber_merchant_id: restaurant.uber_merchant_id ?? "",
    active: restaurant.active,
    autopilot_enabled: restaurant.autopilot_enabled,
  };
}

export default function EditRestaurantPage() {
  const { user } = useAuth();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const restaurantId = Number(params.id);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [form, setForm] = useState<RestaurantForm | null>(null);
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [gmailMapping, setGmailMapping] = useState<GmailRestaurantMapping | null>(null);
  const [storeMappings, setStoreMappings] = useState<UberStoreMapping[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [savingGmailMapping, setSavingGmailMapping] = useState(false);
  const [saved, setSaved] = useState(false);
  const [gmailSaved, setGmailSaved] = useState(false);

  useEffect(() => {
    if (!Number.isFinite(restaurantId)) {
      setError(new Error("Restaurant invalide."));
      setLoading(false);
      return;
    }

    async function loadData() {
      const [restaurantData, accountData, mappingData, storeData] = await Promise.all([
        api.getRestaurant(restaurantId),
        api.getGmailAccounts().catch(() => [] as EmailAccount[]),
        api.getGmailRestaurantMappings().catch(() => [] as GmailRestaurantMapping[]),
        api.getUberStoreMappings().catch(() => [] as UberStoreMapping[]),
      ]);
      setRestaurant(restaurantData);
      setForm(restaurantToForm(restaurantData));
      setAccounts(accountData);
      setGmailMapping(mappingData.find((mapping) => mapping.restaurant_id === restaurantId) ?? null);
      setStoreMappings(storeData.filter((mapping) => mapping.restaurant_id === restaurantId));
    }

    loadData()
      .catch(setError)
      .finally(() => setLoading(false));
  }, [restaurantId]);

  if (user?.role !== "owner") {
    return <EmptyState title="Acces reserve owner" />;
  }

  if (loading) {
    return <LoadingState label="Chargement du restaurant" />;
  }

  if (!form || !restaurant) {
    return (
      <section className="page-section">
        <ApiError error={error} />
        <EmptyState title="Restaurant introuvable" />
      </section>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form) {
      return;
    }

    setSubmitting(true);
    setError(null);
    setSaved(false);

    try {
      const updated = await api.updateRestaurant(restaurantId, {
        name: form.name.trim(),
        legal_name: emptyToNull(form.legal_name),
        address: emptyToNull(form.address),
        phone_number: emptyToNull(form.phone_number),
        sender_email: form.sender_email.trim(),
        uber_merchant_id: emptyToNull(form.uber_merchant_id),
        active: form.active,
        autopilot_enabled: form.autopilot_enabled,
      });
      setRestaurant(updated);
      setForm(restaurantToForm(updated));
      setSaved(true);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGmailMappingChange(value: string) {
    setSavingGmailMapping(true);
    setError(null);
    setGmailSaved(false);

    try {
      const accountId = value ? Number(value) : null;
      const updated = await api.updateGmailRestaurantMapping(restaurantId, accountId);
      setGmailMapping(updated);
      setGmailSaved(true);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSavingGmailMapping(false);
    }
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Restaurants</p>
          <h1>Modifier restaurant</h1>
        </div>
        <div className="actions">
          <Link href="/restaurants" className="secondary-button">
            Retour restaurants
          </Link>
        </div>
      </div>

      <ApiError error={error} />

      {saved ? (
        <div className="success-box">
          <strong>Restaurant mis a jour</strong>
          <span>{restaurant.name}</span>
        </div>
      ) : null}

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="section-heading">
          <div>
            <h2>Identite restaurant</h2>
            <p className="muted">
              Cette fiche est la source de verite pour les imports Uber, Gmail, preuves et dossiers TENNET.
            </p>
          </div>
          <StatusBadge status={restaurant.active ? "active" : "inactive"} />
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="name">Nom</label>
            <input
              id="name"
              required
              value={form.name}
              onChange={(event) => setForm((current) => (current ? { ...current, name: event.target.value } : current))}
            />
          </div>
          <div className="field">
            <label htmlFor="legal_name">Raison sociale</label>
            <input
              id="legal_name"
              value={form.legal_name}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, legal_name: event.target.value } : current))
              }
            />
          </div>
          <div className="field field--full">
            <label htmlFor="address">Adresse</label>
            <textarea
              id="address"
              value={form.address}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, address: event.target.value } : current))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="phone_number">Telephone restaurant</label>
            <input
              id="phone_number"
              inputMode="tel"
              value={form.phone_number}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, phone_number: event.target.value } : current))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="sender_email">Email fallback du restaurant</label>
            <input
              id="sender_email"
              required
              type="email"
              value={form.sender_email}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, sender_email: event.target.value } : current))
              }
            />
          </div>
          <div className="field">
            <label htmlFor="uber_merchant_id">Uber merchant</label>
            <input
              id="uber_merchant_id"
              value={form.uber_merchant_id}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, uber_merchant_id: event.target.value } : current))
              }
            />
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.active}
              onChange={(event) => setForm((current) => (current ? { ...current, active: event.target.checked } : current))}
            />
            Restaurant actif
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.autopilot_enabled}
              onChange={(event) =>
                setForm((current) => (current ? { ...current, autopilot_enabled: event.target.checked } : current))
              }
            />
            AutoPilot active pour ce restaurant
          </label>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Enregistrement" : "Enregistrer"}
          </button>
          <button type="button" className="secondary-button" onClick={() => router.push("/restaurants")}>
            Annuler
          </button>
        </div>
      </form>

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Compte Gmail Uber</h2>
            <p className="muted">
              Choisis le compte Gmail qui correspond a ce restaurant. TENNET utilise ce mapping pour les brouillons,
              les reponses Uber et les relances.
            </p>
          </div>
          <StatusBadge status={gmailMapping?.email_account_id ? "active" : "manual_review"} />
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="gmail_account">Compte Gmail lie</label>
            <select
              id="gmail_account"
              value={gmailMapping?.email_account_id ?? ""}
              disabled={savingGmailMapping || accounts.length === 0}
              onChange={(event) => void handleGmailMappingChange(event.target.value)}
            >
              <option value="">Aucun compte choisi</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.email_address ?? `Compte #${account.id}`}
                </option>
              ))}
            </select>
          </div>
          <DetailItem label="Compte actuel" value={gmailMapping?.email_address ?? "Aucun compte choisi"} />
          <DetailItem
            label="Derniere mise a jour"
            value={gmailMapping?.updated_at ? formatDate(gmailMapping.updated_at) : "-"}
          />
        </div>
        {accounts.length === 0 ? (
          <p className="muted">Aucun compte Gmail connecte. Va dans Parametres Gmail puis reviens mapper ce restaurant.</p>
        ) : null}
        {gmailSaved ? (
          <div className="success-box">
            <strong>Mapping Gmail enregistre</strong>
            <span>{gmailMapping?.email_address ?? "Aucun compte choisi"}</span>
          </div>
        ) : null}
        <div className="actions">
          <Link href="/settings/email" className="secondary-button">
            Gerer comptes Gmail
          </Link>
        </div>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Stores Uber lies</h2>
            <p className="muted">
              Ces mappings evitent que TENNET associe une commande Uber au mauvais restaurant.
            </p>
          </div>
          <StatusBadge status={storeMappings.length > 0 ? "active" : "manual_review"} />
        </div>
        {storeMappings.length > 0 ? (
          <div className="restaurant-linked-list">
            {storeMappings.map((mapping) => (
              <article className="restaurant-linked-item" key={mapping.id}>
                <div>
                  <strong>{mapping.uber_store_name}</strong>
                  <span>{mapping.uber_store_id}</span>
                </div>
                <StatusBadge status={mapping.active ? "active" : "inactive"} />
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">Aucun store Uber lie pour ce restaurant.</p>
        )}
        <div className="actions">
          <Link href="/uber/stores" className="button">
            Ajouter store Uber
          </Link>
          <Link href="/uber/unmapped-stores" className="secondary-button">
            Mapper stores non reconnus
          </Link>
        </div>
      </section>
    </section>
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
