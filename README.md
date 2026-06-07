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
- `GET|POST /v1/orders/{id}/drafts`
- `GET /v1/drafts`
- `GET /v1/dashboard/summary`

Le service de validation verifie qu'une commande contient les informations et preuves bloquantes avant de passer le dossier a `ready_to_send`. Un dossier incomplet passe a `missing_evidence`. Aucun brouillon d'email n'est genere par cette validation.

Le service de brouillons cree uniquement des contenus internes a partir des donnees existantes du dossier. Un brouillon initial ne peut etre cree que pour une commande `ready_to_send` et complete. Il ne declenche aucun envoi reel.

## Demarrage rapide

1. Copier le fichier d'environnement :

```bash
cp .env.example .env
```

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

Cette premiere base ne contient pas :

- d'integration Gmail ;
- d'integration OpenAI API ;
- d'envoi reel d'email ;
- d'envoi Gmail, Microsoft Graph ou SMTP ;
- de relance automatique.

Les fichiers sont stockes localement en developpement dans `backend/storage`.
