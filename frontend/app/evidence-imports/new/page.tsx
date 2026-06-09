"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import ApiError from "@/components/ApiError";
import LoadingState from "@/components/LoadingState";
import { api, type Restaurant } from "@/lib/api";

export default function NewEvidenceImportPage() {
  const router = useRouter();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [restaurantId, setRestaurantId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api
      .getRestaurants()
      .then(setRestaurants)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(kind: "files" | "zip") {
    setSubmitting(true);
    setError(null);
    try {
      const selectedRestaurantId = restaurantId ? Number(restaurantId) : null;
      const batch =
        kind === "zip"
          ? await api.createEvidenceZipImport(zipFile as File, selectedRestaurantId)
          : await api.createEvidenceImport(files, selectedRestaurantId);
      router.push(`/evidence-imports/${batch.id}`);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <LoadingState label="Chargement restaurants" />;
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Preuves</p>
          <h1>Nouvel import massif</h1>
          <p>Importez vos tickets, photos de gaspillage, captures Uber et preuves en vrac.</p>
        </div>
        <Link href="/evidence-imports" className="secondary-button">
          Retour
        </Link>
      </div>

      <ApiError error={error} />

      <section className="tool-panel">
        <div className="field">
          <label htmlFor="restaurant_id">Restaurant optionnel</label>
          <select id="restaurant_id" value={restaurantId} onChange={(event) => setRestaurantId(event.target.value)}>
            <option value="">Tous / a determiner</option>
            {restaurants.map((restaurant) => (
              <option key={restaurant.id} value={restaurant.id}>
                {restaurant.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid-two">
          <div className="tool-panel">
            <h2>Multi-fichiers</h2>
            <input type="file" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
            <button type="button" className="button" disabled={submitting || files.length === 0} onClick={() => handleSubmit("files")}>
              Importer fichiers
            </button>
          </div>
          <div className="tool-panel">
            <h2>Archive ZIP</h2>
            <input type="file" accept=".zip" onChange={(event) => setZipFile(event.target.files?.[0] ?? null)} />
            <button type="button" className="button" disabled={submitting || !zipFile} onClick={() => handleSubmit("zip")}>
              Importer ZIP
            </button>
          </div>
        </div>
      </section>
    </section>
  );
}
