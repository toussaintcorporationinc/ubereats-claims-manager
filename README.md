# Uber Eats Claims Manager

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
- import massif CSV/XLSX des commandes annulees ;
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

Les commandes peuvent aussi etre importees en masse depuis `/imports/new` avec un fichier CSV ou XLSX. Le backend analyse les lignes, detecte erreurs, doublons et restaurants non autorises, puis cree uniquement les lignes valides lors de la confirmation.

Les brouillons internes peuvent etre transformes en brouillons Gmail reels lorsque `EMAIL_PROVIDER_ENABLED=true` et que l'OAuth Gmail est configure. Cette integration utilise les scopes `gmail.compose` et `gmail.readonly`, joint les preuves de la commande si demande et n'envoie jamais l'email automatiquement. L'envoi Gmail est possible uniquement apres confirmation manuelle explicite depuis l'application.

Les reponses Gmail peuvent etre synchronisees manuellement lorsque `GMAIL_INBOUND_SYNC_ENABLED=true`. Les messages entrants sont dedupliques, rattaches par thread Gmail ou numero de commande Uber, puis affiches dans `/inbox` et dans l'historique email de la commande. Aucune reponse automatique n'est generee.

Un owner ou manager peut ensuite traiter manuellement une reponse Uber rattachee depuis `/inbox` ou le detail commande. Le traitement enregistre un `ClaimResponseReview`, marque le message comme revu ou ignore, met a jour le statut commercial de la commande si necessaire (`accepted`, `payment_to_verify`, `payment_confirmed`, `refused` ou `manual_review`) et cree des `AuditLog`. Aucun email ni relance n'est declenche par cette action.

Les relances controlees se recalculent depuis `/followups`. La politique V1 propose `followup_1` a J+2, `followup_2` a J+5, `escalation` a J+10 et `manual_review` a J+15 ou quand la limite de relances est atteinte. Les taches creent des brouillons internes puis, si Gmail est configure, des brouillons Gmail. Aucun envoi automatique n'est implemente ; l'envoi reste manuel et confirme via le workflow Gmail existant.

Les rapports commerciaux sont disponibles depuis `/reports`. Ils permettent de suivre les montants reclames, recuperes, en attente ou refuses, les taux de reussite, les performances par restaurant, les relances et les reponses Uber traitees. Les exports CSV/XLSX sont reserves aux roles `owner` et `manager`, respectent les restaurants autorises et n'incluent pas les noms clients par defaut.

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

## Production

La configuration production est fournie par :

- `docker-compose.prod.yml` ;
- `.env.production.example` ;
- `deploy/Caddyfile` ;
- `scripts/backup_postgres.sh` ;
- `scripts/restore_postgres.sh` ;
- `scripts/backup_evidence_files.sh` ;
- `scripts/healthcheck.sh`.

Demarrage type :

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml exec backend alembic upgrade head
```

En production, le backend refuse les secrets placeholders, SQLite, CORS wildcard et `DEBUG=true`.

## Perimetre actuel

Cette base contient une integration Gmail limitee a la creation de brouillons, a leur envoi manuel approuve et a la lecture/rattachement des reponses. Elle ne contient pas :

- d'integration OpenAI API ;
- d'envoi automatique ;
- de reponse automatique ;
- d'envoi Microsoft Graph ou SMTP ;
- de relance automatique infinie.

Les fichiers sont stockes localement en developpement dans `backend/storage`.
