"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import ApiError from "@/components/ApiError";
import { api } from "@/lib/api";

export default function NewImportPage() {
  const router = useRouter();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      if (!selectedFile) {
        throw new Error("Selectionnez un fichier CSV ou XLSX.");
      }
      const preview = await api.previewOrderImport(selectedFile);
      router.push(`/imports/${preview.batch_id}`);
    } catch (apiError) {
      setError(apiError);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Imports</p>
          <h1>Analyser un fichier commandes</h1>
        </div>
        <Link href="/imports" className="secondary-button">
          Retour imports
        </Link>
      </div>

      <ApiError error={error} />

      <form className="tool-panel" onSubmit={handleSubmit}>
        <div className="form-grid">
          <div className="field field--full">
            <label htmlFor="import_file">Fichier CSV ou XLSX</label>
            <input
              id="import_file"
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              required
              onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            />
          </div>
        </div>
        <div className="actions">
          <button type="submit" className="button" disabled={submitting}>
            {submitting ? "Analyse" : "Analyser"}
          </button>
        </div>
      </form>
    </section>
  );
}
