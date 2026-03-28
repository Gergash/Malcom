"""
credits.py: lógica de créditos / paywall por usuario (chat_id).

- No depende de AnalystAgent: separa lógica comercial del análisis.
- La persistencia vive en app/database/quota_manager.py (SQLite).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    # `python -m app.main`
    from app.database.quota_manager import DEFAULT_FREE_MESSAGE_LIMIT, QuotaManager
except ModuleNotFoundError:
    # `python main.py` desde `app/`
    from database.quota_manager import DEFAULT_FREE_MESSAGE_LIMIT, QuotaManager


@dataclass
class UserCredits:
    message_count: int = 0
    is_premium: bool = False
    free_message_limit: int = DEFAULT_FREE_MESSAGE_LIMIT

    def should_paywall(self) -> bool:
        return (not self.is_premium) and self.message_count >= self.free_message_limit

    def bump_message_count(self, n: int = 1) -> None:
        self.message_count = max(0, int(self.message_count) + int(n))


def check_and_bump(
    quota: QuotaManager,
    chat_id: int,
    *,
    free_message_limit: int = DEFAULT_FREE_MESSAGE_LIMIT,
    bump_by: int = 1,
) -> Optional[str]:
    """
    Retorna un string de bloqueo si aplica paywall, si no: incrementa el contador y retorna None.
    Persistencia en SQLite.
    """
    # La tabla tiene su propio free_message_limit; mantenemos free_message_limit aquí
    # como configuración por defecto (se puede extender luego).
    paywalled = quota.bump_and_check(chat_id=int(chat_id), bump_by=int(bump_by))
    return "PAYWALL_TRIGGER" if paywalled else None

