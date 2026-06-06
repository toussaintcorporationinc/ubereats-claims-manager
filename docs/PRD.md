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

