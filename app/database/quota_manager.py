"""
quota_manager.py: persistencia de cuota (7 mensajes) y premium en SQLite.

Objetivo:
- Separar lógica comercial del bot y del AnalystAgent.
- Persistir por chat_id (Telegram) en disco.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_FREE_MESSAGE_LIMIT = 7


@dataclass
class QuotaState:
    chat_id: int
    message_count: int
    is_premium: bool
    free_message_limit: int = DEFAULT_FREE_MESSAGE_LIMIT

    def should_paywall(self) -> bool:
        return (not self.is_premium) and self.message_count >= self.free_message_limit


class QuotaManager:
    def __init__(self, db_path: Optional[str] = None):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        default_path = os.path.join(project_root, "database", "quota.db")
        self._db_path = os.path.abspath(db_path or default_path)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_quota (
                        chat_id INTEGER PRIMARY KEY,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        is_premium INTEGER NOT NULL DEFAULT 0,
                        free_message_limit INTEGER NOT NULL DEFAULT 7,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def get_state(self, chat_id: int) -> QuotaState:
        now = int(time.time())
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT chat_id, message_count, is_premium, free_message_limit FROM user_quota WHERE chat_id=?",
                    (int(chat_id),),
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO user_quota(chat_id, message_count, is_premium, free_message_limit, updated_at) VALUES(?,?,?,?,?)",
                        (int(chat_id), 0, 0, DEFAULT_FREE_MESSAGE_LIMIT, now),
                    )
                    conn.commit()
                    return QuotaState(
                        chat_id=int(chat_id),
                        message_count=0,
                        is_premium=False,
                        free_message_limit=DEFAULT_FREE_MESSAGE_LIMIT,
                    )
                return QuotaState(
                    chat_id=int(row[0]),
                    message_count=int(row[1]),
                    is_premium=bool(int(row[2])),
                    free_message_limit=int(row[3]),
                )
            finally:
                conn.close()

    def set_premium(self, chat_id: int, is_premium: bool) -> None:
        now = int(time.time())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO user_quota(chat_id, message_count, is_premium, free_message_limit, updated_at)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        is_premium=excluded.is_premium,
                        updated_at=excluded.updated_at
                    """,
                    (int(chat_id), 0, 1 if is_premium else 0, DEFAULT_FREE_MESSAGE_LIMIT, now),
                )
                conn.commit()
            finally:
                conn.close()

    def bump_and_check(self, chat_id: int, bump_by: int = 1) -> bool:
        """
        Incrementa contador si NO está paywalled.
        Retorna True si debe bloquearse (PAYWALL), False si se permite y se incrementó.
        """
        now = int(time.time())
        with self._lock:
            conn2 = self._connect()
            try:
                row = conn2.execute(
                    "SELECT message_count, is_premium, free_message_limit FROM user_quota WHERE chat_id=?",
                    (int(chat_id),),
                ).fetchone()
                if row is None:
                    # Crear registro y permitir el primer bump
                    conn2.execute(
                        "INSERT INTO user_quota(chat_id, message_count, is_premium, free_message_limit, updated_at) VALUES(?,?,?,?,?)",
                        (int(chat_id), 0, 0, DEFAULT_FREE_MESSAGE_LIMIT, now),
                    )
                    row = (0, 0, DEFAULT_FREE_MESSAGE_LIMIT)

                message_count, is_premium_i, free_limit = int(row[0]), int(row[1]), int(row[2])
                should_paywall = (is_premium_i == 0) and (message_count >= free_limit)
                if should_paywall:
                    return True
                new_count = message_count + int(bump_by)
                conn2.execute(
                    "UPDATE user_quota SET message_count=?, updated_at=? WHERE chat_id=?",
                    (new_count, now, int(chat_id)),
                )
                conn2.commit()
                return False
            finally:
                conn2.close()

