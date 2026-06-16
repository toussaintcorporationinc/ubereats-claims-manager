import MachineImportHero from "@/components/MachineImportHero";

export default function AnnulationsPage() {
  return (
    <section className="page-section page-section--simple">
      <MachineImportHero
        eyebrow="Annulations Uber"
        title="Annulations"
        description="Tickets, exports, photos ou ZIP : depose les preuves de commandes annulees en masse, TENNET rapproche les annulations, verifie les paiements et garde les blocages visibles."
        instruction="IMPORTEZ LES PREUVES DE DEMANDE D'ANNULATION"
        fileButtonLabel="Deposer preuves d'annulation"
        trigger="cancellations"
      />

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

    </section>
  );
}
