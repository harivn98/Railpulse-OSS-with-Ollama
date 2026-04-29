"""
RailPulse OSS — async SQLAlchemy engine and session factory.

Uses `asyncpg` as the PostgreSQL driver and exposes:
  - `engine`           — the shared async engine.
  - `AsyncSessionLocal` — a session-maker for dependency injection.
  - `Base`             — declarative base for ORM models.
  - `get_session()`    — FastAPI dependency that yields a session per request.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def get_session():
    """FastAPI dependency — yields one async session per request."""
    async with AsyncSessionLocal() as session:
        yield session
