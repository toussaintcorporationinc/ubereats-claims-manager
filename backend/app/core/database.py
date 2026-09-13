from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings
from app.core.sealed_database_config import decrypt_sealed_database_url


class Base(DeclarativeBase):
    pass


settings = get_settings()

database_url = settings.database_url
local_database_url = "localhost" in database_url or "127.0.0.1" in database_url
if local_database_url and (settings.vercel or settings.runtime_environment == "production"):
    database_url = decrypt_sealed_database_url(settings.jwt_secret_key)
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
