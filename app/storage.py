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
            conn.execute("""CREATE TABLE IF NOT EXISTS user_memory (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT,
                last_seen TEXT NOT NULL,
                messages TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (chat_id, user_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS clan_memory (\n                id INTEGER PRIMARY KEY AUTOINCREMENT,\n                chat_id INTEGER NOT NULL,\n                memory TEXT NOT NULL,\n                created_at TEXT NOT NULL\n            )""")\n            conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                correction TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
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

    def is_chat_enabled(self, chat_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT enabled FROM chat_settings WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO chat_settings(chat_id, enabled, updated_at) VALUES(?,?,?)",
                    (chat_id, 1, datetime.now(timezone.utc).isoformat()),
                )
                return True
            return bool(row[0])

    def set_chat_enabled(self, chat_id: int, enabled: bool):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO chat_settings(chat_id, enabled, updated_at)
                   VALUES(?,?,?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                       enabled=excluded.enabled,
                       updated_at=excluded.updated_at""",
                (chat_id, 1 if enabled else 0, datetime.now(timezone.utc).isoformat()),
            )


    def remember_user(self, chat_id: int, user_id: int | None, username: str | None, display_name: str | None, message: str | None = None):
        if user_id is None:
            return
        with self._conn() as conn:
            row = conn.execute(
                "SELECT messages FROM user_memory WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            history = [x for x in (row[0].split("\n") if row and row[0] else []) if x]
            if message:
                history.append(message.strip()[:500])
                history = history[-10:]
            conn.execute(
                """INSERT INTO user_memory(chat_id,user_id,username,display_name,last_seen,messages)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(chat_id,user_id) DO UPDATE SET
                       username=excluded.username,
                       display_name=excluded.display_name,
                       last_seen=excluded.last_seen,
                       messages=excluded.messages""",
                (chat_id, user_id, username, display_name, datetime.now(timezone.utc).isoformat(), "\n".join(history)),
            )

    def user_last_seen(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            row = conn.execute("SELECT last_seen FROM user_memory WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row[0] if row else None


    def add_clan_memory(self, chat_id: int, memory: str):
        memory = memory.strip()
        if not memory:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO clan_memory(chat_id,memory,created_at) VALUES(?,?,?)",
                (chat_id, memory[:1000], datetime.now(timezone.utc).isoformat()),
            )

    def clan_memories(self, chat_id: int, limit: int = 30):
        with self._conn() as conn:
            return conn.execute(
                "SELECT id, memory, created_at FROM clan_memory WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()

    def user_memories(self, chat_id: int, limit: int = 30):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username, display_name, messages, last_seen FROM user_memory WHERE chat_id=? ORDER BY last_seen DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
        return rows

    def add_knowledge_correction(self, chat_id: int, correction: str):
        correction = correction.strip()
        if not correction:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO knowledge_corrections(chat_id,correction,created_at) VALUES(?,?,?)",
                (chat_id, correction[:1500], datetime.now(timezone.utc).isoformat()),
            )

    def knowledge_corrections(self, chat_id: int, limit: int = 30):
        with self._conn() as conn:
            return conn.execute(
                "SELECT id, correction, created_at FROM knowledge_corrections WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
