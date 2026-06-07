from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes import auth, dashboard, drafts, email, evidence, health, imports, orders, restaurants, users
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
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(restaurants.router)
app.include_router(orders.router)
app.include_router(evidence.router)
app.include_router(drafts.router)
app.include_router(email.router)
app.include_router(imports.router)
app.include_router(dashboard.router)
app.include_router(users.router)
