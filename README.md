# TENNET

Application V1 pour gerer les reclamations Uber Eats de restaurants lorsque des commandes sont annulees apres preparation.

Cette base contient :

- un backend Python FastAPI ;
- une base PostgreSQL ;
- SQLAlchemy et Alembic ;
- Pytest ;
- un frontend Next.js TypeScript ;
- un stockage local de fichiers pour le developpement ;
- un `docker-compose.yml` pour lancer les trois services.

## Domaine V1

Le backend expose maintenant les premiers objets metier :

- restaurants ;
- commandes a reclamer ;
- fichiers de preuve ;
- brouillons internes d'email ;
- fils email historisables sans integration externe ;
- audit logs ;
- authentification JWT simple ;
- roles owner, manager et staff ;
- service de validation des dossiers de reclamation ;
- service de generation de brouillons internes d'email ;
- upload local securise des fichiers de preuve ;
- file de demandes de preuves et upload mobile par lien tokenise ;
- import massif CSV/XLSX des commandes annulees ;
- detection et suivi des deductions Uber / remboursements clients depuis transactions importees ;
- creation de vrais brouillons Gmail via OAuth ;
- envoi manuel approuve de brouillons Gmail, sans automatisation ;
- lecture et rattachement manuel des reponses Gmail entrantes ;
- traitement manuel des reponses Uber et mise a jour des statuts de reclamation ;
- relances controlees J+2/J+5/J+10/J+15 sous forme de taches et brouillons, sans envoi automatique ;
- reporting commercial avec exports CSV/XLSX ;
- dashboard de synthese.

Les endpoints principaux sont :

- `GET /health`
- `GET /ready`
- `GET /version`
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `GET /v1/auth/me`
- `GET|POST /v1/users`
- `GET|PATCH /v1/users/{id}`
- `POST /v1/users/{id}/restaurants`
- `DELETE /v1/users/{id}/restaurants/{restaurant_id}`
- `GET|POST /v1/restaurants`
- `GET|PATCH /v1/restaurants/{id}`
- `GET|POST /v1/orders`
- `GET|PATCH /v1/orders/{id}`
- `POST /v1/orders/{id}/validate`
- `GET|POST /v1/orders/{id}/evidence`
- `POST /v1/orders/{id}/evidence/upload`
- `GET /v1/evidence/{id}/download`
- `GET /v1/evidence-tasks`
- `POST /v1/evidence-tasks/recalculate`
- `POST /v1/evidence-tasks/{id}/upload`
- `POST /v1/evidence-tasks/{id}/upload-link`
- `GET|POST /v1/evidence-upload-links/{token}`
- `POST /v1/customer-refunds/detect`
- `GET /v1/customer-refunds`
- `GET /v1/customer-refunds/{id}`
- `POST /v1/customer-refunds/{id}/recalculate-evidence`
- `POST /v1/customer-refunds/{id}/create-claim-order`
- `POST /v1/customer-refunds/{id}/create-draft`
- `POST /v1/customer-refunds/{id}/create-gmail-draft`
- `POST /v1/customer-refunds/{id}/reviews`
- `GET /v1/customer-refunds/{id}/reviews`
- `POST /v1/customer-refunds/{id}/ignore`
- `GET /v1/customer-refund-reviews`
- `GET /v1/recovery/summary`
- `GET /v1/recovery/cases`
- `GET /v1/recovery/actions`
- `GET /v1/recovery/export/summary.xlsx`
- `GET /v1/recovery/export/cases.csv`
- `GET|POST /v1/orders/{id}/drafts`
- `GET /v1/drafts`
- `GET /v1/email/gmail/status`
- `GET /v1/email/gmail/oauth/start`
- `GET /v1/email/gmail/oauth/callback`
- `POST /v1/email/gmail/disconnect`
- `POST /v1/drafts/{id}/gmail-draft`
- `POST /v1/email/gmail/provider-drafts/{id}/send`
- `GET /v1/email/gmail/inbound/status`
- `POST /v1/email/gmail/inbound/sync`
- `GET /v1/email/inbound-messages`
- `POST /v1/email/inbound-messages/{id}/link`
- `GET /v1/orders/{id}/email-messages`
- `POST /v1/orders/{id}/response-reviews`
- `GET /v1/orders/{id}/response-reviews`
- `GET /v1/response-reviews`
- `GET /v1/followups/due`
- `POST /v1/followups/recalculate`
- `POST /v1/followups/{id}/create-draft`
- `POST /v1/followups/{id}/create-gmail-draft`
- `POST /v1/followups/{id}/skip`
- `POST /v1/followups/{id}/complete`
- `GET /v1/reports/commercial-summary`
- `GET /v1/reports/orders`
- `GET /v1/reports/followups`
- `GET /v1/reports/responses`
- `GET /v1/reports/export/orders.csv`
- `GET /v1/reports/export/orders.xlsx`
- `GET /v1/reports/export/followups.csv`
- `GET /v1/reports/export/responses.csv`
- `GET /v1/reports/export/commercial-summary.xlsx`
- `GET /v1/dashboard/summary`
- `POST /v1/imports/orders/preview`
- `GET /v1/imports`
- `GET /v1/imports/{id}`
- `GET /v1/imports/{id}/rows`
- `POST /v1/imports/{id}/confirm`
- `POST /v1/imports/{id}/cancel`

Le service de validation verifie qu'une commande contient les informations et preuves bloquantes avant de passer le dossier a `ready_to_send`. Un dossier incomplet passe a `missing_evidence`. Aucun brouillon d'email n'est genere par cette validation.

Le service de brouillons cree uniquement des contenus internes a partir des donnees existantes du dossier. Un brouillon initial ne peut etre cree que pour une commande `ready_to_send` et complete. Il ne declenche aucun envoi reel.

Les preuves peuvent etre ajoutees par upload local securise depuis le detail d'une commande. Les fichiers acceptes sont PDF et images courantes (`jpg`, `png`, `webp`, `heic`, `heif`) avec limite de taille configurable. Les telechargements passent toujours par l'API protegee.

Les preuves manquantes peuvent aussi etre pilotees depuis `/evidence-tasks`. TENNET recalcule les demandes de preuves a partir des dossiers incomplets et des resultats de reconciliation Uber qui exigent des justificatifs. Un owner ou manager peut creer un lien mobile tokenise pour une demande precise. Le token brut est retourne une seule fois, seul son hash est stocke, et l'upload public reste limite a la preuve demandee. Aucun email n'est envoye automatiquement.

Les deductions Uber et remboursements clients peuvent etre detectes depuis les transactions financieres importees. TENNET identifie les refunds, chargebacks, ajustements negatifs et motifs comme commande non recue ou article manquant, cree des exigences de preuves, puis laisse un owner ou manager creer le dossier et les brouillons. Les decisions Uber sur ces deductions sont traitees manuellement avec historique de review, montant recupere, refus, paiement a verifier ou preuves demandees. Aucune contestation n'est envoyee automatiquement.

Les commandes peuvent aussi etre importees en masse depuis `/imports/new` avec un fichier CSV ou XLSX. Le backend analyse les lignes, detecte erreurs, doublons et restaurants non autorises, puis cree uniquement les lignes valides lors de la confirmation.

Les brouillons internes peuvent etre transformes en brouillons Gmail reels lorsque `EMAIL_PROVIDER_ENABLED=true` et que l'OAuth Gmail est configure. Cette integration utilise les scopes `gmail.compose`, `gmail.send` et `gmail.readonly`, joint les preuves de la commande si demande et n'envoie jamais l'email automatiquement. L'envoi Gmail est possible uniquement apres confirmation manuelle explicite depuis l'application.

Les reponses Gmail peuvent etre synchronisees manuellement lorsque `GMAIL_INBOUND_SYNC_ENABLED=true`. Les messages entrants sont dedupliques, rattaches par thread Gmail ou numero de commande Uber, puis affiches dans `/inbox` et dans l'historique email de la commande. Aucune reponse automatique n'est generee.

Un owner ou manager peut ensuite traiter manuellement une reponse Uber rattachee depuis `/inbox` ou le detail commande. Le traitement enregistre un `ClaimResponseReview`, marque le message comme revu ou ignore, met a jour le statut commercial de la commande si necessaire (`accepted`, `payment_to_verify`, `payment_confirmed`, `refused` ou `manual_review`) et cree des `AuditLog`. Aucun email ni relance n'est declenche par cette action.

Les relances controlees se recalculent depuis `/followups`. La politique V1 propose `followup_1` a J+2, `followup_2` a J+5, `escalation` a J+10 et `manual_review` a J+15 ou quand la limite de relances est atteinte. Les taches creent des brouillons internes puis, si Gmail est configure, des brouillons Gmail. Aucun envoi automatique n'est implemente ; l'envoi reste manuel et confirme via le workflow Gmail existant.

Le cockpit recuperation est disponible depuis `/recovery`. Il unifie commandes annulees non compensees, resultats de reconciliation Uber, deductions clients, preuves manquantes, relances et outcomes. Il affiche les montants detectes, contestables, en attente de preuve, envoyes, recuperes, refuses et a revue manuelle. TENNET ne garantit pas le remboursement ; il garantit le suivi et la revue systematique des pertes detectees.

Les rapports commerciaux sont disponibles depuis `/reports`. Ils permettent de suivre les montants reclames, recuperes, en attente ou refuses, les taux de reussite, les performances par restaurant, les relances, les reponses Uber traitees et les deductions clients. Les exports CSV/XLSX sont reserves aux roles `owner` et `manager`, respectent les restaurants autorises et n'incluent pas les noms clients par defaut.

## Demarrage rapide

1. Copier le fichier d'environnement :

```bash
cp .env.example .env
```

Le stockage local des preuves utilise `EVIDENCE_STORAGE_BACKEND=local`, `EVIDENCE_STORAGE_DIR` et `MAX_EVIDENCE_FILE_SIZE_MB`.
Les imports utilisent `IMPORT_STORAGE_DIR` et `IMPORT_MAX_FILE_SIZE_MB`.
Gmail reste desactive par defaut avec `EMAIL_PROVIDER_ENABLED=false`. Pour tester la creation, l'envoi manuel et la lecture des reponses Gmail, renseigner `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, `GMAIL_OAUTH_REDIRECT_URI`, `GMAIL_SCOPES`, `DEFAULT_UBER_EATS_SUPPORT_EMAIL`, `EMAIL_MAX_ATTACHMENT_TOTAL_MB`, puis activer `GMAIL_INBOUND_SYNC_ENABLED=true` pour la sync entrante.
Les delais de relance sont configurables via `FOLLOWUP_1_DELAY_DAYS`, `FOLLOWUP_2_DELAY_DAYS`, `ESCALATION_DELAY_DAYS`, `MANUAL_REVIEW_AFTER_DAYS` et `MAX_FOLLOWUPS_PER_ORDER`. `FOLLOWUP_AUTOMATIC_SEND_ENABLED` reste `false` par defaut et ne declenche aucun envoi dans cette V1.
Les exports utilisent `EXPORT_MAX_ROWS` pour limiter le volume et `REPORT_DEFAULT_LOOKBACK_DAYS` comme fenetre indicative de reporting.
Les demandes de preuves utilisent `EVIDENCE_TASK_HIGH_AMOUNT`, `EVIDENCE_TASK_URGENT_AMOUNT`, `EVIDENCE_UPLOAD_LINK_EXPIRY_HOURS` et `EVIDENCE_UPLOAD_LINK_MAX_USES`.

2. Lancer les services :

```bash
docker compose up --build
```

3. Ouvrir les services :

- Frontend : http://localhost:3000
- Backend health check : http://localhost:8000/health
- PostgreSQL : `localhost:5432`

4. Creer le premier owner :

- ouvrir http://localhost:3000/setup-owner ;
- ou appeler `POST /v1/auth/register`.

Apres creation du premier owner, l'inscription publique est fermee. Les utilisateurs suivants sont crees par un owner depuis `/users`.

## Commandes utiles

### Backend local

Depuis la racine :

```bash
cd backend
python -m venv .venv
```

Activation Windows :

```powershell
.\.venv\Scripts\Activate.ps1
```

Activation Linux/macOS :

```bash
source .venv/bin/activate
```

Installation et verification :

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
pytest -q
python -m compileall -q app
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend local

```bash
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

### Docker

```bash
docker compose up --build
```

Valider la configuration Docker Compose :

```bash
docker compose config
```

Lancer les tests backend dans Docker :

```bash
docker compose exec backend pytest
```

Arreter les services :

```bash
docker compose down
```

Supprimer les volumes locaux de base de donnees :

```bash
docker compose down -v
```

Documentation CI et developpement : `docs/CI.md`.
Documentation securite et roles : `docs/SECURITY.md`.
Documentation production : `docs/DEPLOYMENT.md`, `docs/OPERATIONS.md`, `docs/BACKUP_RESTORE.md` et `docs/PRODUCTION_CHECKLIST.md`.
Documentation go-live V1 : `docs/GO_LIVE_RUNBOOK.md`, `docs/ACCEPTANCE_TEST_PLAN.md`, `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, `docs/GMAIL_PRODUCTION_VALIDATION.md`, `docs/ROLLBACK_PLAN.md`, `docs/RELEASE_NOTES_V1.md` et `docs/KNOWN_LIMITATIONS_V1.md`.

## Production

La configuration production est fournie par :

- `docker-compose.prod.yml` ;
- `.env.production.example` ;
- `deploy/Caddyfile` ;
- `scripts/backup_postgres.sh` ;
- `scripts/restore_postgres.sh` ;
- `scripts/backup_evidence_files.sh` ;
- `scripts/healthcheck.sh` ;
- `scripts/smoke_test.sh`.

Demarrage type :

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

En production, le backend refuse les secrets placeholders, SQLite, CORS wildcard et `DEBUG=true`.

Avant lancement, executer le plan de recette `docs/ACCEPTANCE_TEST_PLAN.md`, le runbook `docs/GO_LIVE_RUNBOOK.md` et le smoke test :

```bash
API_URL=https://api.example.com FRONTEND_URL=https://app.example.com ./scripts/smoke_test.sh
```

## Perimetre actuel

Cette base contient une integration Gmail limitee a la creation de brouillons, a leur envoi manuel approuve et a la lecture/rattachement des reponses. Elle ne contient pas :

- d'integration OpenAI API ;
- d'envoi automatique ;
- de reponse automatique ;
- d'envoi Microsoft Graph ou SMTP ;
- de relance automatique infinie.

Les fichiers sont stockes localement en developpement dans `backend/storage`.

## Connecteur Uber Eats

Mission 18 prepare TENNET a une integration officielle Uber Eats sans scraping ni automatisation de navigateur :

- page `/uber` pour l'etat de strategie d'acces ;
- page `/uber/stores` pour mapper un restaurant TENNET vers un `uber_store_id` ;
- page `/uber/reconciliation` pour importer des rapports Uber Eats Manager CSV/XLSX et detecter les commandes annulees non compensees ;
- endpoints `/v1/uber/*` pour statut, mappings, import reporting et reconciliation.

La V1 du connecteur ne fait aucun appel API Uber reel. Les imports de rapports restent le fallback jusqu'a approbation Uber et obtention de credentials officiels.

Mission 19 ajoute le workflow d'import reporting sur plusieurs mois :

- `/uber/reporting/new` : upload CSV/XLSX et choix `orders_report`, `payments_report`, `adjustments_report` ou `combined_report` ;
- preview avec colonnes detectees, lignes invalides, warnings et stores non mappes ;
- `/uber/reporting/{batch_id}` : confirmation de l'import apres controle ;
- `/uber/unmapped-stores` : mapping explicite des stores Uber vers restaurants TENNET.
- `/uber/reconciliation` : analyse 6 mois des commandes annulees et transactions Uber importees ;
- `/uber/reconciliation/runs` : historique des analyses et creation manuelle de dossiers TENNET depuis les resultats eligibles.

Exemples fictifs disponibles :

- `docs/examples/uber_orders_report_template.csv` ;
- `docs/examples/uber_payments_report_template.csv` ;
- `docs/examples/uber_adjustments_report_template.csv`.
