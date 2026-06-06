# Uber Eats Claims Manager

Squelette technique V1 pour une application de gestion de reclamations Uber Eats.

Cette base contient :

- un backend Python FastAPI ;
- une base PostgreSQL ;
- SQLAlchemy et Alembic ;
- Pytest ;
- un frontend Next.js TypeScript ;
- un stockage local de fichiers pour le developpement ;
- un `docker-compose.yml` pour lancer les trois services.

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
- de logique de relance ;
- de logique metier avancee.

Les fichiers sont stockes localement en developpement dans `backend/storage`.
