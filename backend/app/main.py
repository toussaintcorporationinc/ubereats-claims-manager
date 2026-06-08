from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.rate_limit import is_rate_limited
from app.routes import (
    auth,
    dashboard,
    drafts,
    email,
    evidence,
    followups,
    health,
    imports,
    orders,
    reports,
    response_reviews,
    restaurants,
    users,
)
from app.services.file_storage_service import ensure_evidence_storage
from app.services.local_storage import ensure_local_storage
from app.services.order_import_service import ensure_import_storage


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_local_storage()
    ensure_evidence_storage()
    ensure_import_storage()
    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    debug=settings.debug,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def production_hardening_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())

    if is_rate_limited(request):
        response = JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
        )
    else:
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.runtime_environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(restaurants.router)
app.include_router(orders.router)
app.include_router(reports.router)
app.include_router(evidence.router)
app.include_router(drafts.router)
app.include_router(email.router)
app.include_router(followups.router)
app.include_router(imports.router)
app.include_router(dashboard.router)
app.include_router(response_reviews.router)
app.include_router(users.router)
