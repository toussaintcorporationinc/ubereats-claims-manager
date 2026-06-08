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
- dashboard de synthese.

Les endpoints principaux sont :

- `GET /health`
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

## Demarrage rapide

1. Copier le fichier d'environnement :

```bash
cp .env.example .env
```

Le stockage local des preuves utilise `EVIDENCE_STORAGE_BACKEND=local`, `EVIDENCE_STORAGE_DIR` et `MAX_EVIDENCE_FILE_SIZE_MB`.
Les imports utilisent `IMPORT_STORAGE_DIR` et `IMPORT_MAX_FILE_SIZE_MB`.
Gmail reste desactive par defaut avec `EMAIL_PROVIDER_ENABLED=false`. Pour tester la creation, l'envoi manuel et la lecture des reponses Gmail, renseigner `GMAIL_OAUTH_CLIENT_ID`, `GMAIL_OAUTH_CLIENT_SECRET`, `GMAIL_OAUTH_REDIRECT_URI`, `GMAIL_SCOPES`, `DEFAULT_UBER_EATS_SUPPORT_EMAIL`, `EMAIL_MAX_ATTACHMENT_TOTAL_MB`, puis activer `GMAIL_INBOUND_SYNC_ENABLED=true` pour la sync entrante.

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

## Perimetre actuel

Cette base contient une integration Gmail limitee a la creation de brouillons, a leur envoi manuel approuve et a la lecture/rattachement des reponses. Elle ne contient pas :

- d'integration OpenAI API ;
- d'envoi automatique ;
- de reponse automatique ;
- d'envoi Microsoft Graph ou SMTP ;
- de relance automatique.

Les fichiers sont stockes localement en developpement dans `backend/storage`.
