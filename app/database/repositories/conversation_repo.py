"""
conversation_repo.py: persistencia del historial de conversaciones en PostgreSQL.

Cada mensaje (usuario o asistente) se guarda con su chat_id, rol y contenido.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.database.models import Conversation
except ModuleNotFoundError:
    from database.models import Conversation


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_message(self, chat_id: int, role: str, content: str) -> Conversation:
        """Persiste un mensaje. role debe ser 'user' o 'assistant'."""
        msg = Conversation(chat_id=chat_id, role=role, content=content)
        self.db.add(msg)
        await self.db.commit()
        return msg

    async def get_history(self, chat_id: int, limit: int = 20) -> list[Conversation]:
        """Devuelve los últimos `limit` mensajes ordenados del más antiguo al más reciente."""
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.chat_id == chat_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def get_history_as_dicts(self, chat_id: int, limit: int = 20) -> list[dict]:
        """Versión dict-friendly del historial, útil para contexto de los agentes."""
        messages = await self.get_history(chat_id, limit)
        return [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ]
