"use client";

import Link from "next/link";

export default function RemboursementsPage() {
  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero machine-hero--compact">
        <div className="heading-copy">
          <p className="eyebrow">Remboursements Uber</p>
          <h1>Depose les fichiers, TENNET classe et conteste</h1>
          <p>
            Pour les commandes non recues, articles manquants, mauvaises commandes, problemes qualite et ajustements
            negatifs. TENNET garde les preuves, cree les dossiers et lance les actions autorisees.
          </p>
        </div>
        <div className="simple-hero__actions machine-hero__actions">
          <Link href="/dashboard" className="button button--hero">
            Deposer et lancer
          </Link>
          <Link href="/customer-refunds" className="secondary-button">
            Voir dossiers
          </Link>
        </div>
      </div>

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Parcours simple</h2>
            <p className="muted">Un seul chemin pour ne pas te perdre dans les ecrans techniques.</p>
          </div>
        </div>
        <div className="machine-stage-list machine-stage-list--large">
          <article className="machine-stage machine-stage--completed">
            <strong>1. Deposer</strong>
            <span>Exports Uber, preuves ou ZIP</span>
            <small>TENNET lit le contenu sans demander de renommer les fichiers.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>2. Analyser</strong>
            <span>Motifs et montants</span>
            <small>Remboursement client, article manquant, commande non recue, ajustement ou chargeback.</small>
          </article>
          <article className="machine-stage machine-stage--warning">
            <strong>3. Completer</strong>
            <span>Preuves obligatoires</span>
            <small>Ticket, preparation, livraison, sac ou capture Uber selon le type de perte.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>4. Recuperer</strong>
            <span>Email, relance, appel</span>
            <small>AutoPilot agit seulement si Gmail, preuves, limites et restaurant sont correctement configures.</small>
          </article>
        </div>
      </section>
    </section>
  );
}
