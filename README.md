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
- service de validation des dossiers de reclamation ;
- service de generation de brouillons internes d'email ;
- dashboard de synthese.

Les endpoints principaux sont :

- `GET /health`
- `GET|POST /v1/restaurants`
- `GET|PATCH /v1/restaurants/{id}`
- `GET|POST /v1/orders`
- `GET|PATCH /v1/orders/{id}`
- `POST /v1/orders/{id}/validate`
- `GET|POST /v1/orders/{id}/evidence`
- `GET|POST /v1/orders/{id}/drafts`
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

## Commandes utiles

Lancer les tests backend :

```bash
docker compose exec backend pytest
```

Lancer les tests backend localement depuis `backend/` :

```bash
pytest -q
```

Creer une migration Alembic :

```bash
docker compose exec backend alembic revision --autogenerate -m "describe_change"
```

Appliquer les migrations :

```bash
docker compose exec backend alembic upgrade head
```

Arreter les services :

```bash
docker compose down
```

Supprimer les volumes locaux de base de donnees :

```bash
docker compose down -v
```

## Perimetre actuel

Cette premiere base ne contient pas :

- d'integration Gmail ;
- d'integration OpenAI API ;
- d'envoi reel d'email ;
- d'envoi Gmail, Microsoft Graph ou SMTP ;
- de relance automatique.

Les fichiers sont stockes localement en developpement dans `backend/storage`.
