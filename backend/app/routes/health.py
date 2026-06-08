from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.core.database import engine
from app.core.config import get_settings
from app.schemas.health import HealthResponse, ReadyResponse, VersionResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.app_name)


@router.get("/ready", response_model=ReadyResponse)
def readiness_check() -> ReadyResponse:
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = "failed"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        ) from exc

    for label, path in {
        "evidence_storage": settings.evidence_storage_dir,
        "import_storage": settings.import_storage_dir,
    }.items():
        if not writable_directory(path):
            checks[label] = "failed"
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "not_ready", "checks": checks},
            )
        checks[label] = "ok"

    return ReadyResponse(status="ready", checks=checks)


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    settings = get_settings()
    return VersionResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.runtime_environment,
        build_sha=settings.build_sha,
    )


def writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".readycheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        return False
    return True

