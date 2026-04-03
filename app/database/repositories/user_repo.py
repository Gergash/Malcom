"""
user_repo.py: operaciones CRUD sobre la tabla `users`.

Reemplaza QuotaManager (SQLite) con PostgreSQL async.
Soporta identidad dual: chat_id (Telegram) + email (web/pago).
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

    # ── Búsqueda ──────────────────────────────────────────────────────────────

    async def get_by_chat_id(self, chat_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.chat_id == chat_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()

    # ── Creación / upsert ─────────────────────────────────────────────────────

    async def get_or_create(
        self,
        chat_id: int | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> User:
        """
        Obtiene o crea un usuario.
        Estrategia de vinculación:
          1. Busca por chat_id si se provee.
          2. Busca por email si se provee.
          3. Si encuentra uno, actualiza los campos vacíos.
          4. Si no encuentra ninguno, crea un nuevo registro.
        """
        user: User | None = None

        if chat_id is not None:
            user = await self.get_by_chat_id(chat_id)

        if user is None and email:
            user = await self.get_by_email(email)
            # Vincular chat_id al usuario encontrado por email
            if user is not None and chat_id is not None and user.chat_id is None:
                user.chat_id = chat_id
                user.updated_at = datetime.utcnow()
                await self.db.commit()
                await self.db.refresh(user)

        if user is None:
            user = User(
                chat_id=chat_id,
                email=email.lower().strip() if email else None,
                username=username,
                free_message_limit=settings.free_message_limit,
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)

        return user

    async def link_email(self, chat_id: int, email: str) -> User:
        """
        Asocia un email permanente a un chat_id de Telegram.
        Es el puente entre la identidad volátil (chat_id) y la identidad
        web persistente (email) necesaria para el webhook de pago.
        """
        email = email.lower().strip()

        # ¿Hay otro usuario con ese email?
        existing = await self.get_by_email(email)
        if existing is not None and existing.chat_id != chat_id:
            # Fusionar: el usuario con email ya existe, vincular su chat_id
            await self.db.execute(
                update(User)
                .where(User.email == email)
                .values(chat_id=chat_id, updated_at=datetime.utcnow())
            )
            # Eliminar el duplicado con chat_id sin email si existe
            orphan = await self.get_by_chat_id(chat_id)
            if orphan is not None and orphan.id != existing.id:
                await self.db.delete(orphan)
            await self.db.commit()
            return await self.get_by_email(email)  # type: ignore[return-value]

        user = await self.get_or_create(chat_id=chat_id)
        user.email = email
        user.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ── Paywall / créditos ────────────────────────────────────────────────────

    async def get_state(self, chat_id: int | None = None, email: str | None = None) -> dict:
        """Devuelve el estado actual de créditos sin modificar el contador."""
        if chat_id is not None:
            user = await self.get_or_create(chat_id=chat_id)
        elif email is not None:
            user = await self.get_or_create(email=email)
        else:
            raise ValueError("Se requiere chat_id o email")

        remaining = user.free_message_limit - user.message_count
        return {
            "chat_id": user.chat_id,
            "email": user.email,
            "username": user.username,
            "message_count": user.message_count,
            "is_premium": user.is_premium,
            "free_message_limit": user.free_message_limit,
            "credits_remaining": max(0, remaining),
            "paywall": (not user.is_premium) and (user.message_count >= user.free_message_limit),
            "premium_since": user.premium_since.isoformat() if user.premium_since else None,
        }

    async def bump_and_check(
        self,
        chat_id: int | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> dict:
        """
        Middleware de cuota: incrementa el contador y evalúa el paywall.

        Regla de negocio:
            if not user.is_premium and user.message_count >= 7:
                return PAYWALL_TRIGGER

        Retorna:
            {
                "paywall": bool,          # True → bloquear antes de llamar al agente
                "credits_remaining": int  # mensajes restantes (-1 si premium)
            }
        """
        user = await self.get_or_create(chat_id=chat_id, username=username, email=email)

        if user.is_premium:
            return {"paywall": False, "credits_remaining": -1}

        # ── PAYWALL CHECK ─────────────────────────────────────────────────────
        if user.message_count >= user.free_message_limit:
            return {"paywall": True, "credits_remaining": 0}

        # Incrementar contador
        user.message_count += 1
        user.updated_at = datetime.utcnow()
        await self.db.commit()

        remaining = user.free_message_limit - user.message_count
        return {"paywall": False, "credits_remaining": max(0, remaining)}

    # ── Premium / pagos ───────────────────────────────────────────────────────

    async def activate_premium(
        self,
        chat_id: int | None = None,
        email: str | None = None,
    ) -> User:
        """
        Activa el plan premium para un usuario identificado por chat_id o email.
        Llamado desde el webhook de pago una vez confirmado el cobro.
        """
        user = await self.get_or_create(chat_id=chat_id, email=email)
        if not user.is_premium:
            user.is_premium = True
            user.premium_since = datetime.utcnow()
            user.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def set_premium(self, chat_id: int, is_premium: bool = True) -> User:
        """Alias de activate_premium para compatibilidad con código existente."""
        if is_premium:
            return await self.activate_premium(chat_id=chat_id)
        await self.db.execute(
            update(User)
            .where(User.chat_id == chat_id)
            .values(is_premium=False, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.get_by_chat_id(chat_id)  # type: ignore[return-value]
