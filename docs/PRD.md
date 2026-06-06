# PRD - Uber Eats Claims Manager

## Objectif

Uber Eats Claims Manager aide a centraliser le suivi des reclamations liees aux commandes Uber Eats d'un ou plusieurs restaurants.

La V1 technique pose uniquement la base applicative :

- backend FastAPI ;
- base PostgreSQL ;
- migrations Alembic ;
- frontend Next.js TypeScript ;
- stockage local de fichiers en developpement ;
- tests backend de base.

## Utilisateurs cibles

- proprietaire ou operateur de restaurant ;
- equipe administrative chargee du suivi des remboursements ;
- futur support interne pour traiter les pieces justificatives.

## Perimetre fonctionnel vise pour une V1 produit

- liste des restaurants ;
- liste des commandes ;
- creation et suivi de reclamations ;
- pieces jointes locales en developpement ;
- statuts de traitement ;
- preparation de brouillons d'emails.

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

