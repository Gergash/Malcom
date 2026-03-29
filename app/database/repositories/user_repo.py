"""
user_repo.py: operaciones CRUD sobre la tabla `users`.

Reemplaza QuotaManager (SQLite) con PostgreSQL async.
Mantiene la misma semántica de paywall: bump_and_check() incrementa
el contador y devuelve si debe bloquearse.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.database.models import User
    from app.core.config import get_settings
except ModuleNotFoundError:
    from database.models import User
    from core.config import get_settings

settings = get_settings()


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_or_create(self, chat_id: int, username: str | None = None) -> User:
        """Obtiene el usuario o lo crea si no existe."""
        result = await self.db.execute(select(User).where(User.chat_id == chat_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                chat_id=chat_id,
                username=username,
                free_message_limit=settings.free_message_limit,
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def get_state(self, chat_id: int) -> dict:
        """Devuelve el estado actual de créditos del usuario."""
        user = await self.get_or_create(chat_id)
        remaining = user.free_message_limit - user.message_count
        return {
            "chat_id": user.chat_id,
            "message_count": user.message_count,
            "is_premium": user.is_premium,
            "free_message_limit": user.free_message_limit,
            "credits_remaining": max(0, remaining),
            "paywall": (not user.is_premium) and (user.message_count >= user.free_message_limit),
        }

    async def bump_and_check(self, chat_id: int, username: str | None = None) -> dict:
        """
        Incrementa el contador de mensajes y evalúa el paywall.

        Retorna:
            {
                "paywall": bool,          # True → bloquear, no procesar
                "credits_remaining": int  # mensajes restantes (-1 si premium)
            }
        """
        user = await self.get_or_create(chat_id, username)

        if user.is_premium:
            return {"paywall": False, "credits_remaining": -1}

        # Verificar antes de incrementar
        if user.message_count >= user.free_message_limit:
            return {"paywall": True, "credits_remaining": 0}

        # Incrementar
        user.message_count += 1
        user.updated_at = datetime.utcnow()
        await self.db.commit()

        remaining = user.free_message_limit - user.message_count
        return {"paywall": False, "credits_remaining": max(0, remaining)}

    async def set_premium(self, chat_id: int, is_premium: bool = True) -> User:
        """Activa o desactiva el plan premium de un usuario."""
        await self.db.execute(
            update(User)
            .where(User.chat_id == chat_id)
            .values(is_premium=is_premium, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        result = await self.db.execute(select(User).where(User.chat_id == chat_id))
        return result.scalar_one()
