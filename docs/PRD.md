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
- ajout de preuves locales ;
- consultation de brouillons internes d'emails ;
- journalisation des creations importantes ;
- dashboard de synthese.

## Workflow utilisateur V1

1. L'utilisateur ouvre le dashboard.
2. Il cree un restaurant.
3. Il cree une commande contestee rattachee au restaurant.
4. Il ouvre le detail de la commande.
5. Il ajoute les metadonnees des preuves obligatoires :
   - `cancellation_proof` ;
   - `preparation_proof` ou `waste_photo`.
6. Il valide le dossier.
7. Si le dossier est incomplet, l'interface affiche les elements manquants et les raisons bloquantes.
8. Si le dossier est complet, le statut passe a `ready_to_send`.
9. Il genere un brouillon interne initial.
10. Le brouillon apparait dans le detail commande et dans la page globale des brouillons.
11. Aucun email reel n'est envoye.

## Modeles metier V1

- `Restaurant` : etablissement, email expediteur et identifiant marchand Uber ;
- `ClaimOrder` : commande annulee apres preparation, montant reclame, statut et resultat ;
- `EvidenceFile` : preuve locale attachee a une commande ;
- `EmailDraft` : brouillon interne, sans envoi reel ;
- `EmailThread` : futur historique des conversations email ;
- `AuditLog` : trace des actions importantes.

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

