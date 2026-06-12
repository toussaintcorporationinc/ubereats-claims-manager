# TENNET

Application V1 pour gerer les reclamations Uber Eats de restaurants lorsque des commandes sont annulees apres preparation.

## Domaines officiels

Le domaine officiel TENNET est `thetennet.com`.

- Production : `https://thetennet.com` redirige vers `https://app.thetennet.com`, API `https://api.thetennet.com`
- Staging : `https://staging-app.thetennet.com` et `https://staging-api.thetennet.com`

Le domaine Resend verifie est `mail.thetennet.com`. Resend reste desactive par defaut, sans cle API dans le depot. Gmail reste separe pour les conversations Uber et les envois Gmail controles. Aucun envoi automatique, aucune relance automatique et aucune analyse OpenAI reelle ne sont actives par defaut.

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
- station preuves terrain avec ticket imprimable, QR code et file priorisee mobile ;
- import massif de preuves existantes avec analyse controlee et rattachement manuel ;
- import massif CSV/XLSX des commandes annulees ;
- detection et suivi des deductions Uber / remboursements clients depuis transactions importees ;
- creation de vrais brouillons Gmail via OAuth ;
- routage multi-Gmail par restaurant pour utiliser la bonne boite Uber ;
- envoi manuel approuve de brouillons Gmail, plus AutoPilot controle si explicitement active ;
- lecture, rattachement et sync planifiee optionnelle des reponses Gmail entrantes ;
- analyse controlee des reponses Gmail Uber, avec decisions positives/negatives tracees et appels ouverts apres refus ;
- envoi transactionnel Resend optionnel, desactive par defaut et confirme manuellement ;
- traitement manuel des reponses Uber et mise a jour des statuts de reclamation ;
- workflow d'appels persistants apres refus Uber ;
- relances controlees J+2/J+5/J+10/J+15 sous forme de taches et brouillons, avec envoi AutoPilot seulement si active ;
- AutoPilot V1.2 pour envois Gmail controles, desactive par defaut, avec dry-run, limites, cooldown et arret d'urgence ;
- reporting commercial avec exports CSV/XLSX ;
- dashboard de synthese.
- contrat app native terrain pour camera et imprimante ticket, sans lecture tablette Uber.

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
- `GET /v1/autopilot/status`
- `POST /v1/autopilot/dry-run`
- `POST /v1/autopilot/run`
- `POST /v1/autopilot/stop`
- `GET /v1/autopilot/runs`
- `GET /v1/autopilot/actions`
- `GET|POST /v1/orders`
- `GET|PATCH /v1/orders/{id}`
- `POST /v1/orders/{id}/validate`
- `GET|POST /v1/orders/{id}/evidence`
- `POST /v1/orders/{id}/evidence/upload`
- `GET /v1/evidence/{id}/download`
- `GET /v1/evidence-tasks`
- `GET /v1/live-evidence/station`
- `POST /v1/evidence-tasks/recalculate`
- `POST /v1/evidence-tasks/{id}/upload`
- `POST /v1/evidence-tasks/{id}/upload-link`
- `POST /v1/evidence-tasks/{id}/print-ticket`
- `GET|POST /v1/evidence-upload-links/{token}`
- `POST /v1/evidence-imports`
- `POST /v1/evidence-imports/zip`
- `GET /v1/evidence-imports`
- `GET /v1/evidence-imports/{id}`
- `GET /v1/evidence-imports/{id}/files`
- `POST /v1/evidence-imports/{id}/analyze`
- `POST /v1/evidence-imports/{id}/bulk-accept-high-confidence`
- `GET /v1/evidence-imported-files/{id}`
- `GET /v1/evidence-imported-files/{id}/preview`
- `POST /v1/evidence-imported-files/{id}/attach`
- `POST /v1/evidence-imported-files/{id}/ignore`
- `POST /v1/evidence-match-candidates/{id}/accept`
- `POST /v1/evidence-match-candidates/{id}/reject`
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
- `GET /v1/appeals`
- `GET /v1/appeals/{id}`
- `POST /v1/appeals/recalculate`
- `POST /v1/appeals/{id}/analyze-refusal`
- `POST /v1/appeals/{id}/create-draft`
- `POST /v1/appeals/{id}/create-gmail-draft`
- `POST /v1/appeals/{id}/mark-sent`
- `POST /v1/appeals/{id}/pause`
- `POST /v1/appeals/{id}/manual-close`
- `POST /v1/appeals/{id}/reopen`
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
- `POST /v1/email/gmail/inbound/analyze`
- `GET /v1/email/inbound-messages`
- `POST /v1/email/inbound-messages/{id}/analyze`
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

Les preuves manquantes peuvent aussi etre pilotees depuis `/evidence-tasks`. TENNET recalcule les demandes de preuves a partir des dossiers incomplets et des resultats de reconciliation Uber qui exigent des justificatifs. Un owner ou manager peut creer un lien mobile tokenise pour une demande precise. Le token brut est retourne une seule fois, seul son hash est stocke, et l'upload public reste limite a la preuve demandee. Un ticket preuve imprimable peut aussi etre cree pour guider le terrain : il contient la commande, le type de preuve attendu et un QR code vers l'upload mobile de cette tache. Aucun email n'est envoye automatiquement.

Les preuves existantes peuvent etre importees en masse depuis `/evidence-imports`. TENNET stocke les fichiers, analyse localement ou via fournisseur desactive par defaut, puis propose des rattachements vers commandes, taches de preuve, deductions Uber ou resultats de reconciliation. L'attachement automatique reste desactive par defaut et aucun rattachement faible n'est force.

Les deductions Uber et remboursements clients peuvent etre detectes depuis les transactions financieres importees. TENNET identifie les refunds, chargebacks, ajustements negatifs et motifs comme commande non recue ou article manquant, cree des exigences de preuves, puis laisse un owner ou manager creer le dossier et les brouillons. Les decisions Uber sur ces deductions sont traitees manuellement avec historique de review, montant recupere, refus, paiement a verifier ou preuves demandees. Aucune contestation n'est envoyee automatiquement.

Les commandes peuvent aussi etre importees en masse depuis `/imports/new` avec un fichier CSV ou XLSX. Le backend analyse les lignes, detecte erreurs, doublons et restaurants non autorises, puis cree uniquement les lignes valides lors de la confirmation.

Les brouillons internes peuvent etre transformes en brouillons Gmail reels lorsque `EMAIL_PROVIDER_ENABLED=true` et que l'OAuth Gmail est configure. Cette integration utilise les scopes `gmail.compose`, `gmail.send` et `gmail.readonly`, joint les preuves de la commande si demande et n'envoie automatiquement que dans le cadre AutoPilot explicitement active avec ses garde-fous.

Les reponses Gmail peuvent etre synchronisees manuellement ou planifiees avec `GMAIL_INBOUND_AUTO_SYNC_ENABLED=true` lorsque `GMAIL_INBOUND_SYNC_ENABLED=true`. Les messages entrants sont dedupliques, rattaches par thread Gmail ou numero de commande Uber, puis affiches dans `/inbox` et dans l'historique email de la commande. Les emails non rattaches, hors Uber ou ambigus ne declenchent pas d'envoi.

Un owner ou manager peut ensuite traiter manuellement une reponse Uber rattachee depuis `/inbox` ou le detail commande. Le traitement enregistre un `ClaimResponseReview`, marque le message comme revu ou ignore, met a jour le statut commercial de la commande si necessaire (`accepted`, `payment_to_verify`, `payment_confirmed`, `refused` ou `manual_review`) et cree des `AuditLog`. Une reponse negative fiable peut declencher un appel AutoPilot si AutoPilot est active globalement et sur le restaurant.

Les relances controlees se recalculent depuis `/followups`. La politique V1 propose `followup_1` a J+2, `followup_2` a J+5, `escalation` a J+10 et `manual_review` a J+15 ou quand la limite de relances est atteinte. Les taches creent des brouillons internes puis, si Gmail est configure, des brouillons Gmail. AutoPilot peut envoyer les taches eligibles seulement si les flags et limites sont actifs.

Le cockpit recuperation est disponible depuis `/recovery`. Il unifie commandes annulees non compensees, resultats de reconciliation Uber, deductions clients, preuves manquantes, relances et outcomes. Il affiche les montants detectes, contestables, en attente de preuve, envoyes, recuperes, refuses et a revue manuelle. TENNET ne garantit pas le remboursement ; il garantit le suivi et la revue systematique des pertes detectees.

Les appels persistants sont disponibles depuis `/appeals`. Un refus Uber cree une action de revue ou d'appel au lieu de cloturer automatiquement le dossier. Un owner ou manager peut analyser le refus, creer un brouillon interne, creer un brouillon Gmail controle, marquer l'appel envoye manuellement, mettre en pause ou cloturer manuellement. AutoPilot peut envoyer les appels eligibles si active, avec cooldown, limites, anti-doublon et arret d'urgence.

Les rapports commerciaux sont disponibles depuis `/reports`. Ils permettent de suivre les montants reclames, recuperes, en attente ou refuses, les taux de reussite, les performances par restaurant, les relances, les reponses Uber traitees et les deductions clients. Les exports CSV/XLSX sont reserves aux roles `owner` et `manager`, respectent les restaurants autorises et n'incluent pas les noms clients par defaut.

## Demarrage rapide

1. Copier le fichier d'environnement :

```bash
cp .env.example .env
```

Le stockage local des preuves utilise `EVIDENCE_STORAGE_BACKEND=local`, `EVIDENCE_STORAGE_DIR` et `MAX_EVIDENCE_FILE_SIZE_MB`.
Les imports utilisent `IMPORT_STORAGE_DIR` et `IMPORT_MAX_FILE_SIZE_MB`.
Gmail reste desactive par defaut avec `EMAIL_PROVIDER_ENABLED=false`. Pour tester la creation, l'envoi et la lecture des reponses Gmail, renseigner `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, `GMAIL_OAUTH_REDIRECT_URI`, `GMAIL_SCOPES`, `DEFAULT_UBER_EATS_SUPPORT_EMAIL`, `EMAIL_MAX_ATTACHMENT_TOTAL_MB`, puis activer `GMAIL_INBOUND_SYNC_ENABLED=true` pour la sync entrante. `GMAIL_INBOUND_AUTO_SYNC_ENABLED=false` par defaut peut etre active pour le zero clic cote serveur.
Les delais de relance sont configurables via `FOLLOWUP_1_DELAY_DAYS`, `FOLLOWUP_2_DELAY_DAYS`, `ESCALATION_DELAY_DAYS`, `MANUAL_REVIEW_AFTER_DAYS` et `MAX_FOLLOWUPS_PER_ORDER`. `FOLLOWUP_AUTOMATIC_SEND_ENABLED` reste `false` par defaut et ne declenche aucun envoi dans cette V1.
Les exports utilisent `EXPORT_MAX_ROWS` pour limiter le volume et `REPORT_DEFAULT_LOOKBACK_DAYS` comme fenetre indicative de reporting.
Les demandes de preuves utilisent `EVIDENCE_TASK_HIGH_AMOUNT`, `EVIDENCE_TASK_URGENT_AMOUNT`, `EVIDENCE_UPLOAD_LINK_EXPIRY_HOURS` et `EVIDENCE_UPLOAD_LINK_MAX_USES`.
L'import massif de preuves utilise `BULK_EVIDENCE_MAX_FILES_PER_BATCH`, `BULK_EVIDENCE_MAX_ZIP_SIZE_MB`, `BULK_EVIDENCE_MAX_FILE_SIZE_MB` et `BULK_EVIDENCE_ALLOWED_EXTENSIONS`. L'analyse de preuves utilise `AI_EVIDENCE_ANALYSIS_ENABLED=false`, `AI_EVIDENCE_AUTO_ATTACH_ENABLED=false`, `AI_EVIDENCE_HIGH_CONFIDENCE_THRESHOLD`, `AI_EVIDENCE_MEDIUM_CONFIDENCE_THRESHOLD`, `OCR_LOCAL_ENABLED`, `OPENAI_API_KEY` et `OPENAI_EVIDENCE_MODEL`.
Les appels persistants utilisent `APPEAL_AUTO_SEND_ENABLED=false`, `APPEAL_MIN_DAYS_BETWEEN_ATTEMPTS`, `APPEAL_MAX_ATTEMPTS_BEFORE_ESCALATION`, `APPEAL_MAX_ATTEMPTS_BEFORE_MANUAL_REVIEW`, `APPEAL_REQUIRE_NEW_ARGUMENT_AFTER_REFUSAL` et `APPEAL_ALLOW_SAME_TEMPLATE_RESEND`.

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
Documentation domaines et Resend : `docs/DOMAIN_MIGRATION_THETENNET.md` et `docs/RESEND_SETUP.md`.
Documentation go-live V1 : `docs/GO_LIVE_RUNBOOK.md`, `docs/ACCEPTANCE_TEST_PLAN.md`, `docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`, `docs/GMAIL_PRODUCTION_VALIDATION.md`, `docs/ROLLBACK_PLAN.md`, `docs/RELEASE_NOTES_V1.md` et `docs/KNOWN_LIMITATIONS_V1.md`.
Documentation V1.1 : `docs/BULK_EVIDENCE_IMPORT.md`, `docs/EVIDENCE_TICKET_PRINTING.md`, `docs/AI_EVIDENCE_ANALYSIS.md`, `docs/PERSISTENT_APPEALS.md`, `docs/CUSTOMER_REFUND_DISPUTES.md`, `docs/RECOVERY_COCKPIT.md` et `docs/UBER_RECONCILIATION_RULES.md`.
Documentation V1.1 finale et staging : `docs/RELEASE_NOTES_V1_1.md`, `docs/RELEASE_NOTES_V1_1_RC.md`, `docs/KNOWN_LIMITATIONS_V1_1.md`, `docs/STAGING_DEPLOYMENT.md`, `docs/STAGING_ACCEPTANCE_PLAN.md` et `docs/V1_1_ACCEPTANCE_TEST_PLAN.md`.

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
API_URL=https://api.thetennet.com FRONTEND_URL=https://app.thetennet.com ./scripts/smoke_test.sh
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

## V1.1 Final Release

`VERSION` vaut `1.1.1-tennet`.

La V1.1 finale ajoute les imports Uber Reporting, la reconciliation 6 mois, les detections de commandes annulees non compensees, les deductions Uber / remboursements clients, les demandes de preuves, l'import massif de preuves, le matching controle, les appels persistants et le cockpit recuperation.

La release patch `1.1.1-tennet` aligne le depot avec les domaines premium `thetennet.com` et documente Resend sur `mail.thetennet.com` en mode desactive par defaut.

Les donnees fictives de recette sont dans `docs/examples/v1_1`. Elles ne doivent pas etre remplacees par des donnees client reelles dans le depot.

Rappels :

- TENNET ne garantit pas le remboursement ;
- TENNET garantit la detection, le suivi, la revue et la tracabilite ;
- aucun refus Uber n'est cloture automatiquement ;
- aucun email, appel ou relance n'est envoye automatiquement sauf AutoPilot explicitement active avec limites ;
- OpenAI/Vision est desactive par defaut ;
- la validation terrain avec de vrais exports Uber reste necessaire avant exploitation commerciale.

## UX premium et Smart Import

Mission 30 ajoute une couche UX premium :

- `/smart-import` accepte CSV, XLSX, PDF, images et ZIP sans renommage obligatoire ;
- les exports Uber avec preambule et deux lignes d'en-tete sont detectes proprement ;
- `/v1/workspace/next-actions` alimente le bloc "A faire maintenant" ;
- mobile et tablette disposent de navigation, cartes responsives et actions principales plus lisibles ;
- une PWA legere permet l'ajout a l'ecran d'accueil sans stockage sensible offline.

Voir `docs/SMART_IMPORT.md`, `docs/MOBILE_USAGE.md`, `docs/DESIGN_SYSTEM.md` et `docs/PREMIUM_UX_PRINCIPLES.md`.

## App native mobile

Une base mobile native Expo/React Native est disponible dans `mobile/tennet-native`.

Elle couvre les usages terrain prioritaires : connexion TENNET, actions urgentes, taches de preuves, photo/PDF, impression de ticket preuve, scan QR de lien mobile tokenise et cockpit recuperation. Elle utilise les permissions backend existantes et ne declenche aucun Gmail, OpenAI, AutoPilot ou envoi automatique.

Voir `docs/NATIVE_MOBILE_APP.md`.
