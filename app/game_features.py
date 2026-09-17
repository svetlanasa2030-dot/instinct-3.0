import logging
import re
import sqlite3
from datetime import datetime, timezone

from app.web_search import search_comeback_cats

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"(?:Продажа|Покупка):\s*([\d\s,.]+)")


def init_game_features(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS item_watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER,
            item TEXT NOT NULL,
            max_price INTEGER,
            created_at TEXT NOT NULL,
            last_snapshot TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            item TEXT NOT NULL,
            sale_price INTEGER,
            buy_price INTEGER,
            created_at TEXT NOT NULL
        )""")


def _parse_price(value: str) -> int | None:
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else None


def extract_prices(text: str) -> tuple[list[int], list[int]]:
    sales, buys = [], []
    for kind, value in re.findall(r"(Продажа|Покупка):\s*([\d\s,.]+)", text or "", re.I):
        price = _parse_price(value)
        if price is None:
            continue
        (sales if kind.lower() == "продажа" else buys).append(price)
    return sales, buys


def add_history(db_path: str, chat_id: int, item: str, snapshot: str):
    sales, buys = extract_prices(snapshot)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        if sales or buys:
            conn.execute(
                "INSERT INTO price_history(chat_id,item,sale_price,buy_price,created_at) VALUES(?,?,?,?,?)",
                (chat_id, item, min(sales) if sales else None, max(buys) if buys else None, now),
            )


def add_watch(db_path: str, chat_id: int, user_id: int | None, item: str, max_price: int | None = None) -> int:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO item_watches(chat_id,user_id,item,max_price,created_at) VALUES(?,?,?,?,?)",
            (chat_id, user_id, item.strip(), max_price, datetime.now(timezone.utc).isoformat()),
        )
        return int(cur.lastrowid)


def list_watches(db_path: str, chat_id: int):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT id,item,max_price FROM item_watches WHERE chat_id=? ORDER BY id",
            (chat_id,),
        ).fetchall()


def remove_watch(db_path: str, chat_id: int, watch_id: int) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM item_watches WHERE id=? AND chat_id=?", (watch_id, chat_id))
        return cur.rowcount > 0


def _best_sale(snapshot: str) -> int | None:
    sales, _ = extract_prices(snapshot)
    return min(sales) if sales else None


def check_watches(db_path: str, send_message):
    """Check active item watches. send_message(chat_id, text) is a sync callback."""
    with sqlite3.connect(db_path) as conn:
        watches = conn.execute("SELECT id,chat_id,user_id,item,max_price,last_snapshot FROM item_watches").fetchall()

    for watch_id, chat_id, user_id, item, max_price, last_snapshot in watches:
        try:
            snapshot = search_comeback_cats(item)
            if not snapshot:
                continue
            add_history(db_path, chat_id, item, snapshot)
            current = _best_sale(snapshot)
            old = _best_sale(last_snapshot or "")
            should_notify = False
            if current is not None and max_price is not None and current <= max_price:
                should_notify = old is None or old > max_price
            elif current is not None and old is not None and current < old:
                should_notify = True

            if should_notify:
                mention = f" для тебя" if user_id else ""
                price_text = f"{current:,}".replace(",", " ")
                send_message(chat_id, f"🔔 Нашла новое предложение{mention}!\n{item}\n💰 Продажа: {price_text}\nПроверь актуальные объявления в котобазе.")

            with sqlite3.connect(db_path) as conn:
                conn.execute("UPDATE item_watches SET last_snapshot=? WHERE id=?", (snapshot, watch_id))
        except Exception as exc:
            logger.exception("Watch %s failed: %s", watch_id, exc)
