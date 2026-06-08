# Backend

Backend FastAPI minimal pour TENNET.

## Commandes

Installer les dependances localement :

```bash
pip install -r requirements.txt
```

Lancer l'API :

```bash
uvicorn app.main:app --reload
```

Lancer les tests :

```bash
pytest
```

Appliquer les migrations :

```bash
alembic upgrade head
```

