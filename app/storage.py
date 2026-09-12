from pathlib import Path
import sqlite3
from datetime import datetime, timezone

class Storage:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def add(self, chat_id: int, user_id: int | None, username: str | None, role: str, content: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages(chat_id,user_id,username,role,content,created_at) VALUES(?,?,?,?,?,?)",
                (chat_id, user_id, username, role, content, datetime.now(timezone.utc).isoformat()),
            )

    def recent(self, chat_id: int, limit: int = 20):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return list(reversed(rows))
