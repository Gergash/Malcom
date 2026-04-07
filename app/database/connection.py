"""
connection.py: motor async de SQLAlchemy para PostgreSQL.

Uso:
    from app.database.connection import AsyncSessionLocal, create_tables

    # Dependency injection en FastAPI:
    async def get_db():
        async with AsyncSessionLocal() as session:
            yield session

    # Crear tablas al arrancar:
    await create_tables()
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

try:
    from app.core.config import get_settings
except ModuleNotFoundError:
    from core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,      # verifica la conexión antes de usar
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency de FastAPI que provee una sesión de base de datos."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Crea todas las tablas definidas en models.py si no existen."""
    try:
        from app.database.models import Base
    except ModuleNotFoundError:
        from database.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True))
