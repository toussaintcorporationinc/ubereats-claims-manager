# CI Quality Gate

La CI GitHub Actions se trouve dans `.github/workflows/ci.yml`.

## Jobs

- `backend` : installe le backend en editable, lance les tests, compile les imports et applique Alembic sur PostgreSQL.
- `frontend` : installe les dependances avec `npm ci`, lance le typecheck et construit Next.js.
- `docker` : valide `docker compose config` et construit les images.
- `quality` : lance des scans basiques contre les secrets evidents et les derives de domaine.

## Commandes locales

Backend :

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

Installation et verification backend :

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
pytest -q
python -m compileall -q app
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend :

```bash
cd frontend
npm ci
npm run typecheck
npm run build
npm run dev
```

Docker :

```bash
docker compose config
docker compose up --build
```

## Variables

Les variables minimales sont documentees dans `.env.example` :

- `DATABASE_URL`
- `BACKEND_CORS_ORIGINS`
- `NEXT_PUBLIC_API_BASE_URL`

`NEXT_PUBLIC_API_BASE_URL` est expose au navigateur et ne doit contenir aucun secret.
