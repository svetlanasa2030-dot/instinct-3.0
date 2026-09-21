from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

AUTHORIZED_USERNAMES = {"hatakepw", "lina_a_bi"}

_COMMAND_RE = re.compile(
    r"(?i)\b(?:напомни(?:ть)?(?:\s+мне)?|напиши(?:\s+в\s+чат)?|отправь(?:\s+в\s+чат)?|сообщение)\b"
)
_DATE_RE = re.compile(r"(?i)\b(сегодня|завтра)\b")
_TIME_RE = re.compile(r"(?i)(?:\bв\s*)?(\d{1,2})[\.:](\d{2})\b|(?:\bв\s*)(\d{1,2})(?=\s|$)")


def is_authorized(username: str | None) -> bool:
    return (username or "").strip().lstrip("@").lower() in AUTHORIZED_USERNAMES


def parse_command(text: str, now: datetime | None = None):
    now = now or datetime.now().astimezone()
    if not re.search(r"(?i)\bалина\b", text):
        return None

    command_match = _COMMAND_RE.search(text)
    if not command_match:
        return None

    time_match = _TIME_RE.search(text)
    if not time_match:
        return None

    hour = int(time_match.group(1) or time_match.group(3))
    minute = int(time_match.group(2) or 0)
    if hour > 23 or minute > 59:
        return None

    date_match = _DATE_RE.search(text)
    day_word = date_match.group(1).lower() if date_match else "today"

    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day_word == "завтра":
        run_at += timedelta(days=1)
    elif run_at <= now:
        run_at += timedelta(days=1)

    # Remove addressing, command, date/time markers and filler words.
    body = re.sub(r"(?i)\bалина\b[,:!\s]*", " ", text)
    body = _COMMAND_RE.sub(" ", body)
    body = _DATE_RE.sub(" ", body)
    body = _TIME_RE.sub(" ", body)
    body = re.sub(r"(?i)\b(мне|в\s+чат|написать|напомнить|напомни|пожалуйста)\b", " ", body)
    body = re.sub(r"\s+", " ", body).strip(" ,.!?")

    if not body:
        return None

    return run_at, body


class ReminderService:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    text TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_messages_due "
                "ON scheduled_messages(sent, run_at)"
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def schedule(self, chat_id: int, user_id: int | None, username: str | None,
                 text: str, run_at: datetime) -> int:
        now = datetime.now().astimezone()
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO scheduled_messages
                   (chat_id,user_id,username,text,run_at,created_at,sent)
                   VALUES(?,?,?,?,?,?,0)""",
                (chat_id, user_id, username, text, run_at.isoformat(), now.isoformat()),
            )
            return int(cur.lastrowid)

    def send_due(self, send_message):
        now = datetime.now().astimezone()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, chat_id, text
                   FROM scheduled_messages
                   WHERE sent=0 AND run_at<=?
                   ORDER BY run_at, id""",
                (now.isoformat(),),
            ).fetchall()

            for reminder_id, chat_id, text in rows:
                try:
                    send_message(chat_id, f"⏰ Напоминание: {text}")
                    conn.execute(
                        "UPDATE scheduled_messages SET sent=1 WHERE id=? AND sent=0",
                        (reminder_id,),
                    )
                except Exception:
                    # Leave it unsent so the next poll can retry.
                    raise


    def list_pending(self, chat_id: int):
        with self._conn() as conn:
            return conn.execute(
                "SELECT id, text, run_at, repeat_rule FROM scheduled_messages WHERE chat_id=? AND sent=0 ORDER BY run_at, id",
                (chat_id,),
            ).fetchall()

    def cancel(self, chat_id: int, reminder_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE scheduled_messages SET sent=1 WHERE id=? AND chat_id=? AND sent=0",
                (reminder_id, chat_id),
            )
            return cur.rowcount > 0
