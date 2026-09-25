import json
import logging
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Google Apps Script Web App.
# Prefer storing these values in %APPDATA%\\InstinctBot\\.env rather than in source code.
GOOGLE_NEWBIE_SECRET = os.getenv("GOOGLE_NEWBIE_SECRET", "").strip()
GOOGLE_NEWBIE_WEBHOOK = os.getenv("GOOGLE_NEWBIE_WEBHOOK", "").strip()


def _refresh_google_config() -> tuple[str, str]:
    """Reload Google settings from the same APPDATA .env used by config.py."""
    global GOOGLE_NEWBIE_SECRET, GOOGLE_NEWBIE_WEBHOOK
    app_data = Path(os.getenv("APPDATA", str(Path.home()))) / "InstinctBot"
    env_path = app_data / ".env"
    load_dotenv(env_path, override=True)
    GOOGLE_NEWBIE_SECRET = os.getenv("GOOGLE_NEWBIE_SECRET", "").strip()
    GOOGLE_NEWBIE_WEBHOOK = os.getenv("GOOGLE_NEWBIE_WEBHOOK", "").strip()
    return GOOGLE_NEWBIE_SECRET, GOOGLE_NEWBIE_WEBHOOK

# Both values are required:
# - GOOGLE_NEWBIE_SECRET: shared secret checked by Google Apps Script
# - GOOGLE_NEWBIE_WEBHOOK: deployed Apps Script Web App URL ending in /exec
# They are intentionally separate values.


def send_newbie_to_google(
    *,
    date: str,
    game_nickname: str,
    level: str,
    class_name: str,
    teamspeak: str,
    telegram: str,
    added_by: str,
) -> bool:
    """Send an accepted newbie to Google Sheets.

    SQLite remains the primary database. A Google failure is deliberately
    non-fatal: the local save has already completed and the bot continues.
    """
    _refresh_google_config()
    if not GOOGLE_NEWBIE_WEBHOOK or not GOOGLE_NEWBIE_SECRET:
        logger.warning(
            "[NEWBIE][GOOGLE] Google storage is not configured. "
            "Set GOOGLE_NEWBIE_SECRET and optionally GOOGLE_NEWBIE_WEBHOOK."
        )
        return False

    payload = json.dumps(
        {
            "secret": GOOGLE_NEWBIE_SECRET,
            "date": date,
            "game_nickname": game_nickname,
            "level": level,
            "class_name": class_name,
            "teamspeak": teamspeak,
            "telegram": telegram,
            "added_by": added_by,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        GOOGLE_NEWBIE_WEBHOOK,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InstinctBot/3.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            if not (200 <= response.status < 300):
                logger.warning(
                    "[NEWBIE][GOOGLE] HTTP %s: %s",
                    response.status,
                    body[:500],
                )
                return False

        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("[NEWBIE][GOOGLE] Invalid JSON response: %s", body[:500])
            return False

        if not result.get("ok"):
            logger.warning("[NEWBIE][GOOGLE] Apps Script error: %s", result)
            return False

        logger.info(
            "[NEWBIE][GOOGLE] Новичок отправлен в Google Sheets: %s",
            game_nickname,
        )
        return True

    except Exception as exc:
        logger.warning(
            "[NEWBIE][GOOGLE] Не удалось отправить '%s': %s",
            game_nickname,
            exc,
        )
        return False


def test_google_newbie() -> tuple[bool, str]:
    """Send a harmless TEST row to Google Sheets and return a user-safe diagnosis."""
    secret, webhook = _refresh_google_config()
    if not secret:
        return False, "Не задан GOOGLE_NEWBIE_SECRET в .env"
    if not webhook:
        return False, "Не задан GOOGLE_NEWBIE_WEBHOOK в .env"

    payload = json.dumps(
        {
            "secret": secret,
            "test": True,
            "date": "TEST",
            "game_nickname": "TEST",
            "level": "TEST",
            "class_name": "TEST",
            "teamspeak": "TEST",
            "telegram": "TEST",
            "added_by": "TEST",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "InstinctBot/3.0 GoogleTest",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
        if not (200 <= status < 300):
            return False, f"HTTP {status}: {body[:300]}"
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            return False, f"Google вернул не JSON: {body[:300]}"
        if not result.get("ok"):
            return False, f"Apps Script отклонил запрос: {str(result)[:300]}"
        return True, "Тестовая запись TEST успешно отправлена в Google Sheets"
    except Exception as exc:
        return False, f"Ошибка подключения: {exc}"
