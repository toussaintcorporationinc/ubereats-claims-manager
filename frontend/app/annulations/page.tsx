"use client";

import Link from "next/link";

export default function AnnulationsPage() {
  return (
    <section className="page-section page-section--simple">
      <div className="machine-hero machine-hero--compact">
        <div className="heading-copy">
          <p className="eyebrow">Annulations Uber</p>
          <h1>Tickets en masse, annulations suivies</h1>
          <p>
            Tu importes les tickets et les exports. TENNET rapproche les commandes annulees, verifie les paiements deja
            accordes, regroupe les preuves et suit les mails Uber.
          </p>
        </div>
        <div className="simple-hero__actions machine-hero__actions">
          <Link href="/smart-import" className="button button--hero">
            Deposer les tickets
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
            <strong>1. Importer sans renommer</strong>
            <span>Rapports Uber + tickets</span>
            <small>CSV, XLSX, PDF, photos ou ZIP. Les doublons exacts sont gardes une seule fois.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>2. Reconciler</strong>
            <span>Compense, partiel, non compense</span>
            <small>TENNET conserve montant commande, montant paye, manque a recuperer et signal deja paye.</small>
          </article>
          <article className="machine-stage machine-stage--warning">
            <strong>3. Regrouper les preuves</strong>
            <span>Ticket, preparation, gaspillage</span>
            <small>Les fichiers douteux restent conserves comme sources a completer, jamais jetes sans trace.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>4. Envoyer et suivre</strong>
            <span>Contestation, relance, appel</span>
            <small>Un refus ne cloture jamais tout seul; les appels restent actifs et les positifs sont comptabilises.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>5. Piloter</strong>
            <span>Argent detecte et recupere</span>
            <small>Le cockpit montre ce qui reste a prouver, envoyer, relancer ou verifier.</small>
          </article>
        </div>
      </section>

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Action suivante</h2>
            <p className="muted">Un seul depart : depot massif. TENNET route ensuite vers reconciliation, preuves et recuperation.</p>
          </div>
        </div>
        <div className="simple-hero__actions">
          <Link href="/smart-import" className="button">
            Importer tickets et exports
          </Link>
          <Link href="/recovery/actions" className="secondary-button">
            Voir actions restantes
          </Link>
        </div>
      </section>
    </section>
  );
}
