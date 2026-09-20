"""Async Postgres test-database engine helpers.

Uses the real Postgres+JSONB dialect against `settings.test_database_url`
(same asyncpg host as the app, different database) — SQLite/aiosqlite is
NOT an option here because `Post.metadata_` uses `postgresql.JSONB`.
"""
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.storage.database import Base
from app.storage import models  # noqa: F401 — populates Base.metadata for create_all


def get_test_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.test_database_url, pool_pre_ping=True)


async def reset_schema(engine: AsyncEngine) -> None:
    """Drop and recreate all tables for a clean, known schema state."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
