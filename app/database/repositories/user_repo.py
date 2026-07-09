"""
user_repo.py: operaciones CRUD sobre la tabla `users`.

Persistencia async sobre PostgreSQL (asyncpg + SQLAlchemy 2.0).
Soporta identidad dual: chat_id (Telegram) + email (web/pago).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.database.models import User
    from app.core.config import get_settings
    from app.quota.daily import next_reset_utc, today_quota_date
except ModuleNotFoundError:
    from database.models import User
    from core.config import get_settings
    from quota.daily import next_reset_utc, today_quota_date

settings = get_settings()


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _today(self) -> date:
        return today_quota_date(settings.quota_timezone)

    def _ensure_daily_reset(self, user: User) -> bool:
        if user.is_premium:
            return False
        today = self._today()
        if user.quota_date is None or user.quota_date < today:
            user.messages_today = 0
            user.quota_date = today
            return True
        return False

    def _state_dict(self, user: User) -> dict:
        reset_at = next_reset_utc(settings.quota_timezone).isoformat()
        if user.is_premium:
            remaining = -1
            paywall = False
        else:
            remaining = max(0, user.free_message_limit - user.messages_today)
            paywall = user.messages_today >= user.free_message_limit
        return {
            "chat_id": user.chat_id,
            "email": user.email,
            "username": user.username,
            "message_count": user.messages_today,
            "messages_today": user.messages_today,
            "daily_limit": user.free_message_limit,
            "messages_remaining_today": remaining,
            "is_premium": user.is_premium,
            "free_message_limit": user.free_message_limit,
            "credits_remaining": remaining,
            "paywall": paywall,
            "premium_since": user.premium_since.isoformat() if user.premium_since else None,
            "quota_resets_at": reset_at,
        }

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
        user: User | None = None

        if chat_id is not None:
            user = await self.get_by_chat_id(chat_id)

        if user is None and email:
            user = await self.get_by_email(email)
            if user is not None and chat_id is not None and user.chat_id is None:
                user.chat_id = chat_id
                user.updated_at = datetime.utcnow()
                await self.db.commit()
                await self.db.refresh(user)

        if user is None:
            today = self._today()
            user = User(
                chat_id=chat_id,
                email=email.lower().strip() if email else None,
                username=username,
                free_message_limit=settings.free_message_limit,
                quota_date=today,
            )
            self.db.add(user)
            await self.db.commit()
            await self.db.refresh(user)

        return user

    async def link_email(self, chat_id: int, email: str) -> User:
        email = email.lower().strip()

        existing = await self.get_by_email(email)
        if existing is not None and existing.chat_id != chat_id:
            await self.db.execute(
                update(User)
                .where(User.email == email)
                .values(chat_id=chat_id, updated_at=datetime.utcnow())
            )
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
        if chat_id is not None:
            user = await self.get_or_create(chat_id=chat_id)
        elif email is not None:
            user = await self.get_or_create(email=email)
        else:
            raise ValueError("Se requiere chat_id o email")

        if self._ensure_daily_reset(user):
            user.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(user)

        return self._state_dict(user)

    async def bump_and_check(
        self,
        chat_id: int | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> dict:
        user = await self.get_or_create(chat_id=chat_id, username=username, email=email)

        if user.is_premium:
            return {"paywall": False, "credits_remaining": -1}

        if self._ensure_daily_reset(user):
            user.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(user)

        if user.messages_today >= user.free_message_limit:
            return {"paywall": True, "credits_remaining": 0}

        user.messages_today += 1
        user.message_count += 1
        user.updated_at = datetime.utcnow()
        await self.db.commit()

        remaining = max(0, user.free_message_limit - user.messages_today)
        return {"paywall": False, "credits_remaining": remaining}

    # ── Premium / pagos ───────────────────────────────────────────────────────

    async def activate_premium(
        self,
        chat_id: int | None = None,
        email: str | None = None,
    ) -> User:
        user = await self.get_or_create(chat_id=chat_id, email=email)
        if not user.is_premium:
            user.is_premium = True
            user.premium_since = datetime.utcnow()
            user.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(user)
        return user

    async def set_premium(self, chat_id: int, is_premium: bool = True) -> User:
        if is_premium:
            return await self.activate_premium(chat_id=chat_id)
        await self.db.execute(
            update(User)
            .where(User.chat_id == chat_id)
            .values(is_premium=False, updated_at=datetime.utcnow())
        )
        await self.db.commit()
        return await self.get_by_chat_id(chat_id)  # type: ignore[return-value]
