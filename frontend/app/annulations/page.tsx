"use client";

import Link from "next/link";

export default function AnnulationsPage() {
  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero machine-hero--compact">
        <div className="heading-copy">
          <p className="eyebrow">Annulations Uber</p>
          <h1>Preuves en masse, contestation propre</h1>
          <p>
            Pour les commandes annulees apres preparation. Tu importes les exports et les photos; TENNET rapproche les
            commandes, calcule les montants manquants et prepare la suite.
          </p>
        </div>
        <div className="simple-hero__actions machine-hero__actions">
          <Link href="/dashboard" className="button button--hero">
            Deposer et lancer
          </Link>
          <Link href="/uber/reconciliation" className="secondary-button">
            Voir analyse
          </Link>
        </div>
      </div>

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Parcours annulation</h2>
            <p className="muted">TENNET garde la logique financiere et les preuves ensemble.</p>
          </div>
        </div>
        <div className="machine-stage-list machine-stage-list--large">
          <article className="machine-stage machine-stage--completed">
            <strong>1. Importer</strong>
            <span>Rapports Uber + preuves</span>
            <small>CSV, XLSX, PDF, photos ou ZIP, meme avec noms de fichiers sales.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>2. Reconciler</strong>
            <span>Compense / non compense</span>
            <small>TENNET conserve le montant commande, montant paye et manque a recuperer.</small>
          </article>
          <article className="machine-stage machine-stage--warning">
            <strong>3. Associer</strong>
            <span>Ticket, preparation, gaspillage</span>
            <small>Les fichiers douteux restent conserves et visibles, jamais jetes sans trace.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>4. Suivre</strong>
            <span>Relance et appel</span>
            <small>Un refus ne cloture jamais tout seul; les appels restent actifs.</small>
          </article>
        </div>
      </section>
    </section>
  );
}
