# PRD - Uber Eats Claims Manager

## Objectif

Uber Eats Claims Manager aide a centraliser le suivi des reclamations liees aux commandes Uber Eats d'un ou plusieurs restaurants.

La V1 pose la base applicative et les premiers objets metier :

- backend FastAPI ;
- base PostgreSQL ;
- migrations Alembic ;
- frontend Next.js TypeScript ;
- stockage local de fichiers en developpement ;
- tests backend metier.

## Utilisateurs cibles

- proprietaire ou operateur de restaurant ;
- equipe administrative chargee du suivi des remboursements ;
- futur support interne pour traiter les pieces justificatives.

## Perimetre fonctionnel vise pour une V1 produit

- creation et mise a jour des restaurants ;
- creation et suivi des commandes a reclamer ;
- prevention des doublons par restaurant et numero de commande Uber Eats ;
- upload de preuves locales securisees ;
- consultation de brouillons internes d'emails ;
- journalisation des creations importantes ;
- authentification et roles utilisateurs ;
- dashboard de synthese.

## Roles utilisateurs V1

- `owner` : acces global, gestion restaurants, gestion utilisateurs, commandes, validation, brouillons et dashboard global.
- `manager` : acces aux restaurants assignes, commandes, preuves, validation, brouillons et dashboard filtre.
- `staff` : acces aux restaurants assignes, creation de commandes, ajout de preuves et consultation. Pas de gestion utilisateurs, pas de creation restaurant, pas de generation de brouillon.

## Workflow utilisateur V1

1. L'utilisateur ouvre le dashboard.
2. Le premier owner initialise l'application via `/setup-owner`.
3. Un owner cree les restaurants et les utilisateurs internes.
4. Un owner assigne les restaurants aux managers et staff concernes.
5. L'utilisateur cree une commande contestee rattachee a un restaurant autorise.
6. Il ouvre le detail de la commande.
7. Il upload les preuves obligatoires :
   - `cancellation_proof` ;
   - `preparation_proof` ou `waste_photo`.
8. Un owner ou manager valide le dossier.
9. Si le dossier est incomplet, l'interface affiche les elements manquants et les raisons bloquantes.
10. Si le dossier est complet, le statut passe a `ready_to_send`.
11. Un owner ou manager genere un brouillon interne initial.
12. Le brouillon apparait dans le detail commande et dans la page globale des brouillons.
13. Aucun email reel n'est envoye.

## Modeles metier V1

- `Restaurant` : etablissement, email expediteur et identifiant marchand Uber ;
- `ClaimOrder` : commande annulee apres preparation, montant reclame, statut et resultat ;
- `EvidenceFile` : fichier de preuve local attache a une commande avec metadonnees, checksum et acces securise ;
- `EmailDraft` : brouillon interne, sans envoi reel ;
- `EmailThread` : futur historique des conversations email ;
- `AuditLog` : trace des actions importantes.
- `User` : utilisateur interne avec role ;
- `UserRestaurantAccess` : association utilisateur restaurant.

## Hors perimetre de cette premiere base

- integration Gmail ;
- integration OpenAI API ;
- envoi reel d'email ;
- relances automatiques ;
- import avance de commandes ;
- automatisation metier des decisions.

## Exigences techniques

- API HTTP exposee avec FastAPI ;
- configuration par variables d'environnement ;
- PostgreSQL comme base de donnees cible ;
- SQLAlchemy comme couche ORM ;
- Alembic pour les migrations ;
- Pytest pour les tests ;
- Next.js TypeScript pour l'interface ;
- Docker Compose pour lancer backend, frontend et base de donnees.

