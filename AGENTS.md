# AGENTS.md

## Projet

Application interne pour gérer les réclamations Uber Eats de plusieurs restaurants, 6 au démarrage, extensible sans limite codée.

Le problème :
Des commandes Uber Eats sont annulées après préparation. Cela crée une perte financière et du gaspillage alimentaire.

Objectif :
Automatiser la création, le suivi et la relance des réclamations auprès d’Uber Eats.

## Règles métier obligatoires

- Ne jamais inventer une information absente.
- Ne jamais inventer un montant.
- Ne jamais inventer une preuve.
- Ne jamais envoyer ou préparer une réclamation sans numéro de commande Uber Eats.
- Ne jamais envoyer ou préparer une réclamation sans restaurant associé.
- Ne jamais envoyer ou préparer une réclamation sans montant.
- Ne jamais envoyer ou préparer une réclamation sans preuve d’annulation.
- Ne jamais envoyer ou préparer une réclamation sans preuve de préparation ou de gaspillage.
- Empêcher les doublons : une même commande Uber Eats ne doit pas être traitée deux fois pour le même restaurant.
- Garder un historique de chaque action.
- La V1 doit créer des brouillons internes, pas envoyer de vrais emails.
- Pas de boucle infinie de relance.
- Les relances doivent être limitées, datées et traçables.

## Stack technique V1

Backend :
- Python
- FastAPI
- PostgreSQL
- SQLAlchemy ou SQLModel
- Alembic
- Pytest

Frontend :
- Next.js
- TypeScript
- interface simple d’administration

Stockage fichiers :
- stockage local en développement
- architecture compatible S3 plus tard

Email :
- V1 : brouillons internes uniquement
- V2 : Gmail API
- V3 : Microsoft Graph si nécessaire

IA :
- V1 : service IA simulé possible
- architecture prête pour OpenAI API plus tard

## Fonctionnalités V1

- Gestion des restaurants
- Création de commandes contestées
- Upload de preuves
- Vérification automatique du dossier
- Génération d’un brouillon de réclamation
- Suivi du statut
- Historique des actions
- Dashboard simple
- Tests backend des règles métier

## Statuts des dossiers

- draft
- missing_evidence
- ready_to_send
- draft_email_created
- sent
- waiting_uber_response
- followup_1_sent
- followup_2_sent
- escalation_sent
- accepted
- payment_to_verify
- payment_confirmed
- refused
- manual_review
- closed

## Qualité attendue

- Code propre et simple.
- Pas de secrets dans le repo.
- Ajouter un fichier .env.example.
- Ajouter un README clair.
- Ajouter docker-compose.yml.
- Ajouter des tests.
- Séparer la logique métier, la base de données, l’IA, les emails et les fichiers.
