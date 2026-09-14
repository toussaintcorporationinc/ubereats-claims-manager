import Link from "next/link";

const sections = [
  {
    title: "Gmail",
    description: "Connecter plusieurs comptes Gmail, reconnecter Google, mapper chaque restaurant et lancer des controles manuels.",
    href: "/settings/email",
    action: "Gerer Gmail",
  },
  {
    title: "Restaurants",
    description: "Creer, modifier, archiver, restaurer et configurer AutoPilot restaurant par restaurant.",
    href: "/restaurants",
    action: "Gerer les restaurants",
  },
  {
    title: "AutoPilot",
    description: "Voir l'etat du moteur automatique, lancer un run manuel, faire un dry-run ou utiliser l'arret d'urgence.",
    href: "/autopilot",
    action: "Ouvrir AutoPilot",
  },
  {
    title: "Utilisateurs",
    description: "Creer les comptes TENNET, attribuer les roles et les acces restaurants.",
    href: "/users",
    action: "Gerer les utilisateurs",
  },
  {
    title: "Relances Gmail",
    description: "Voir les relances, les dossiers surveilles et les actions Gmail en cours.",
    href: "/relance-gmail",
    action: "Ouvrir les relances",
  },
  {
    title: "Reponses Uber",
    description: "Consulter les reponses recues, les rapprochements et les dossiers qui demandent une verification.",
    href: "/inbox",
    action: "Voir les reponses",
  },
  {
    title: "Imports Uber",
    description: "Importer ou verifier manuellement les donnees Uber et les correspondances de magasins.",
    href: "/uber",
    action: "Gerer les imports",
  },
  {
    title: "War Room Gmail",
    description: "Controle avance de la surveillance Gmail, des threads suivis, du backlog et des quotas.",
    href: "/gmail-war-room",
    action: "Ouvrir la War Room",
  },
];

export default function SettingsPage() {
  return (
    <section className="page-section">
      <div className="page-heading">
        <div className="heading-copy">
          <p className="eyebrow">Configuration</p>
          <h1>Parametres TENNET</h1>
          <p>
            Les commandes restent disponibles manuellement. Les moteurs de surveillance Gmail,
            d'analyse, de relance et de suivi continuent de fonctionner automatiquement.
          </p>
        </div>
      </div>

      <div className="restaurant-card-grid">
        {sections.map((section) => (
          <article className="restaurant-card" key={section.href}>
            <div className="stack-sm">
              <h2>{section.title}</h2>
              <p className="muted">{section.description}</p>
            </div>
            <div className="actions">
              <Link href={section.href} className="button">
                {section.action}
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
