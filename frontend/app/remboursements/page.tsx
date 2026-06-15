import MachineImportHero from "@/components/MachineImportHero";

export default function RemboursementsPage() {
  return (
    <section className="page-section page-section--simple">
      <MachineImportHero
        eyebrow="Remboursements Uber"
        title="Remboursements"
        description="Demandes client, commande non recue, article manquant, mauvaise commande ou ajustement negatif : depose les fichiers et preuves en masse, TENNET rattache chaque commande au bon restaurant."
        instruction="IMPORTEZ LES PREUVES DE DEMANDES DE REMBOURSEMENTS"
        fileButtonLabel="Deposer fichiers / preuves"
        trigger="refunds"
      />

      <section className="tool-panel">
        <div className="section-heading">
          <div>
            <h2>Parcours simple</h2>
            <p className="muted">Un seul chemin pour ne pas te perdre dans les ecrans techniques.</p>
          </div>
        </div>
        <div className="machine-stage-list machine-stage-list--large">
          <article className="machine-stage machine-stage--completed">
            <strong>1. Deposer en masse</strong>
            <span>Exports, photos, PDF ou ZIP</span>
            <small>TENNET lit le contenu, detecte les doublons et garde un seul fichier canonique.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>2. Identifier les pertes</strong>
            <span>Motif, commande, client, montant</span>
            <small>Les remboursements vagues restent sources a completer; TENNET n'invente pas une ligne absente.</small>
          </article>
          <article className="machine-stage machine-stage--warning">
            <strong>3. Construire les preuves</strong>
            <span>Ticket, commande, gaspillage</span>
            <small>Objectif terrain : trois preuves propres par dossier quand le cas l'exige.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>4. Envoyer et relancer</strong>
            <span>Email Uber, reponses, appel</span>
            <small>Si Gmail voit deja un paiement positif, TENNET bloque la relance pour eviter les doublons.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>5. Compter le recupere</strong>
            <span>Jour, mois, annee</span>
            <small>Les reponses positives alimentent le suivi; les refus restent actifs pour appel.</small>
          </article>
        </div>
      </section>

    </section>
  );
}
