from pathlib import Path

from app.core.config import get_settings


def ensure_local_storage() -> Path:
    storage_dir = get_settings().local_storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir

