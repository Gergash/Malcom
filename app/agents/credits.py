"""
credits.py: value object de créditos / paywall por usuario.

La persistencia vive exclusivamente en PostgreSQL a través de
app/database/repositories/user_repo.UserRepository.bump_and_check().
Este módulo solo define el dataclass UserCredits para uso como DTO.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_FREE_MESSAGE_LIMIT = 15


@dataclass
class UserCredits:
    message_count: int = 0
    is_premium: bool = False
    free_message_limit: int = DEFAULT_FREE_MESSAGE_LIMIT

    def should_paywall(self) -> bool:
        return (not self.is_premium) and self.message_count >= self.free_message_limit

    def bump_message_count(self, n: int = 1) -> None:
        self.message_count = max(0, int(self.message_count) + int(n))

