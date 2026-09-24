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
            conn.execute("""CREATE TABLE IF NOT EXISTS clan_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                memory TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_corrections (
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
            conn.execute("""CREATE TABLE IF NOT EXISTS recruits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                game_nickname TEXT NOT NULL,
                level TEXT,
                class_name TEXT,
                teamspeak TEXT,
                telegram TEXT,
                added_by_user_id INTEGER,
                added_by_username TEXT,
                added_by_display_name TEXT,
                created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS newbie_drafts (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game_nickname TEXT NOT NULL DEFAULT '',
                level TEXT NOT NULL DEFAULT '',
                class_name TEXT NOT NULL DEFAULT '',
                teamspeak TEXT NOT NULL DEFAULT '',
                telegram TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS newbie_draft_messages (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                questionnaire_message_id INTEGER,
                confirmation_message_id INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
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


    def add_recruit(self, chat_id: int, game_nickname: str, level: str, class_name: str,
                    teamspeak: str, telegram: str, added_by_user_id: int | None,
                    added_by_username: str | None, added_by_display_name: str | None):
        game_nickname = game_nickname.strip()
        if not game_nickname:
            return False
        with self._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM recruits WHERE chat_id=? AND lower(game_nickname)=lower(?) LIMIT 1",
                (chat_id, game_nickname),
            ).fetchone()
            if exists:
                return False
            conn.execute(
                """INSERT INTO recruits(
                    chat_id, game_nickname, level, class_name, teamspeak, telegram,
                    added_by_user_id, added_by_username, added_by_display_name, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    chat_id, game_nickname, level.strip(), class_name.strip(),
                    teamspeak.strip(), telegram.strip(), added_by_user_id,
                    added_by_username.lower().lstrip("@").strip() if added_by_username else None,
                    added_by_display_name, datetime.now(timezone.utc).isoformat(),
                ),
            )
        return True

    def recruits_by_adder(self, chat_id: int, username: str):
        username = username.lower().lstrip("@").strip()
        with self._conn() as conn:
            return conn.execute(
                """SELECT game_nickname, level, class_name, teamspeak, telegram, created_at
                   FROM recruits
                   WHERE chat_id=? AND lower(COALESCE(added_by_username,''))=?
                   ORDER BY id ASC""",
                (chat_id, username),
            ).fetchall()

    def recruits_by_adder_user_id(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            return conn.execute(
                """SELECT game_nickname, level, class_name, teamspeak, telegram, created_at
                   FROM recruits
                   WHERE chat_id=? AND added_by_user_id=?
                   ORDER BY id ASC""",
                (chat_id, user_id),
            ).fetchall()

    def recruit_by_nickname(self, chat_id: int, game_nickname: str):
        with self._conn() as conn:
            return conn.execute(
                """SELECT game_nickname, level, class_name, teamspeak, telegram,
                          added_by_username, added_by_display_name, created_at
                   FROM recruits
                   WHERE chat_id=? AND lower(game_nickname)=lower(?)
                   ORDER BY id DESC LIMIT 1""",
                (chat_id, game_nickname.strip()),
            ).fetchone()

    def save_newbie_draft(self, chat_id: int, user_id: int, data: dict):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO newbie_drafts(
                    chat_id,user_id,game_nickname,level,class_name,teamspeak,telegram,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    game_nickname=excluded.game_nickname,
                    level=excluded.level,
                    class_name=excluded.class_name,
                    teamspeak=excluded.teamspeak,
                    telegram=excluded.telegram,
                    updated_at=excluded.updated_at""",
                (
                    chat_id, user_id,
                    data.get("game_nickname",""),
                    data.get("level",""),
                    data.get("class_name",""),
                    data.get("teamspeak",""),
                    data.get("telegram",""),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def get_newbie_draft(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            row = conn.execute(
                """SELECT game_nickname,level,class_name,teamspeak,telegram
                   FROM newbie_drafts WHERE chat_id=? AND user_id=?""",
                (chat_id, user_id),
            ).fetchone()
        if not row:
            return None
        keys = ("game_nickname","level","class_name","teamspeak","telegram")
        return dict(zip(keys, row))

    def delete_newbie_draft(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM newbie_drafts WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )

    def save_newbie_message_ids(self, chat_id: int, user_id: int, questionnaire_message_id: int | None = None,
                                confirmation_message_id: int | None = None):
        with self._conn() as conn:
            current = conn.execute(
                "SELECT questionnaire_message_id, confirmation_message_id FROM newbie_draft_messages WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            ).fetchone()
            qid = questionnaire_message_id if questionnaire_message_id is not None else (current[0] if current else None)
            cid = confirmation_message_id if confirmation_message_id is not None else (current[1] if current else None)
            conn.execute(
                """INSERT INTO newbie_draft_messages(
                    chat_id,user_id,questionnaire_message_id,confirmation_message_id,updated_at
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    questionnaire_message_id=excluded.questionnaire_message_id,
                    confirmation_message_id=excluded.confirmation_message_id,
                    updated_at=excluded.updated_at""",
                (chat_id, user_id, qid, cid, datetime.now(timezone.utc).isoformat()),
            )

    def get_newbie_message_ids(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            return conn.execute(
                """SELECT questionnaire_message_id, confirmation_message_id
                   FROM newbie_draft_messages WHERE chat_id=? AND user_id=?""",
                (chat_id, user_id),
            ).fetchone()

    def delete_newbie_message_ids(self, chat_id: int, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM newbie_draft_messages WHERE chat_id=? AND user_id=?",
                (chat_id, user_id),
            )
