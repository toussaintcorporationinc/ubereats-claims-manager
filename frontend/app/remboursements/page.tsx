import MachineImportHero from "@/components/MachineImportHero";

export default function RemboursementsPage() {
  return (
    <section className="page-section page-section--simple">
      <MachineImportHero
        eyebrow="Remboursements Uber"
        title="Tickets agrafes, remboursements lances"
        description="Releve la commande en demande de remboursement dans Uber Eats, imprime le ticket, agrafe-le a la commande ou a la preuve terrain, prends la photo et importe tout en masse. GO lance le classement, les preuves, les emails et le suivi."
        instruction="IMPORTEZ LES PREUVES DE DEMANDES DE REMBOURSEMENTS"
        fileButtonLabel="Deposer tickets agrafes"
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
            <strong>1. Relever dans Uber Eats</strong>
            <span>Demande de remboursement</span>
            <small>Tu identifies la commande concernee dans Uber Eats Manager, puis tu imprimes le vrai ticket du restaurant.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>2. Agrafer et photographier</strong>
            <span>Ticket + commande + preuve terrain</span>
            <small>Une photo claire suffit quand elle montre le ticket rattache a la commande ou a la preuve preparee.</small>
          </article>
          <article className="machine-stage machine-stage--warning">
            <strong>3. Importer en masse</strong>
            <span>Photos, PDF, ZIP ou exports</span>
            <small>TENNET lit en profondeur, cherche nom client, numero de commande, date, restaurant et montant dans chaque source.</small>
          </article>
          <article className="machine-stage machine-stage--completed">
            <strong>4. GO</strong>
            <span>Classement, emails, relances</span>
            <small>TENNET lance le parcours remboursements, evite les doublons et bloque les cas deja payes.</small>
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
