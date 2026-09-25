from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot


ROLE_OFFICER = "officer"
ROLE_MEMBER = "member"


class RoleManager:
    """Минимальное отдельное хранилище ролей, не вмешивающееся в Storage."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS bot_roles (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    role TEXT NOT NULL DEFAULT 'member',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )"""
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def get_role(self, chat_id: int, user_id: int) -> str:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT role FROM bot_roles WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
        return row[0] if row else ROLE_MEMBER

    def set_role(
        self,
        chat_id: int,
        user_id: int,
        role: str,
        username: str | None = None,
        display_name: str | None = None,
    ):
        if role not in {ROLE_OFFICER, ROLE_MEMBER}:
            raise ValueError("Недопустимая роль")
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO bot_roles(
                    chat_id, user_id, username, display_name, role, updated_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    username=excluded.username,
                    display_name=excluded.display_name,
                    role=excluded.role,
                    updated_at=excluded.updated_at""",
                (
                    chat_id,
                    user_id,
                    username,
                    display_name,
                    role,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def find_user_by_username(self, chat_id: int, username: str):
        """Ищет участника по username среди уже известных боту пользователей."""
        username = username.lstrip("@").strip().lower()
        if not username:
            return None

        with self._conn() as conn:
            row = conn.execute(
                """SELECT user_id, username, display_name
                   FROM bot_roles
                   WHERE chat_id=? AND LOWER(username)=?
                   LIMIT 1""",
                (chat_id, username),
            ).fetchone()
            if row:
                return row

            row = conn.execute(
                """SELECT user_id, username, display_name
                   FROM user_memory
                   WHERE chat_id=? AND LOWER(username)=?
                   LIMIT 1""",
                (chat_id, username),
            ).fetchone()
        return row

    def list_roles(self, chat_id: int):
        with self._conn() as conn:
            return conn.execute(
                """SELECT user_id, username, display_name, role
                   FROM bot_roles
                   WHERE chat_id=?
                   ORDER BY display_name COLLATE NOCASE, username COLLATE NOCASE""",
                (chat_id,),
            ).fetchall()


async def is_telegram_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {"creator", "administrator"}
    except Exception:
        return False
