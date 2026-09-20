"""
Database connection and session management for Termómetro Cultural.
- Async engine/session for FastAPI (asyncpg).
- Sync engine for Alembic migrations and scripts.
"""
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

settings = get_settings()
Base = declarative_base()

# ---------------------------------------------------------------------------
# Async (application)
# ---------------------------------------------------------------------------
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yield async session for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Sync (Alembic migrations, one-off scripts)
# ---------------------------------------------------------------------------
def get_sync_engine():
    """Create sync engine from DATABASE_URL_SYNC. Used by Alembic env.py and scripts."""
    return create_engine(
        settings.database_url_sync,
        echo=settings.app_env == "development",
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def get_sync_session():
    """Context manager for sync sessions (scripts)."""
    engine = get_sync_engine()
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
