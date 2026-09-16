from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parent.parent
APP_DATA = Path(os.getenv("APPDATA", str(Path.home()))) / "InstinctBot"
APP_DATA.mkdir(parents=True, exist_ok=True)
ENV_PATH = APP_DATA / ".env"
load_dotenv(ENV_PATH, override=True)
# Миграция старой модели, которая больше не доступна в API.
if os.getenv("OPENAI_MODEL", "").strip() == "gpt-5.1-mini":
    os.environ["OPENAI_MODEL"] = "gpt-5.6-luna"


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openai_key: str
    openai_model: str
    group_chat_id: int
    initiative_enabled: bool
    initiative_interval_minutes: int
    db_path: str
    system_prompt: str
    initiative_prompt: str
    google_docs_url: str
    knowledge_refresh_minutes: int
    knowledge_sources: str


def load_settings() -> Settings:
    prompt_path = ROOT / "config" / "prompts.yaml"
    prompts = yaml.safe_load(prompt_path.read_text(encoding="utf-8")) or {}
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    group_id = os.getenv("GROUP_CHAT_ID", "0").strip()
    if not token or not api_key or group_id == "0":
        raise RuntimeError("Заполните Telegram Token, OpenAI API Key и Group Chat ID")

    # Telegram Web/MTProto can show a supergroup ID as -3667294272,
    # while the Bot API expects -1003667294272.
    if group_id.startswith("-") and not group_id.startswith("-100"):
        raw_id = group_id[1:]
        if raw_id.isdigit() and 1000000000 <= int(raw_id) < 1000000000000:
            group_id = "-100" + raw_id
    db_default = str(APP_DATA / "bot.sqlite3")
    return Settings(
        telegram_token=token,
        openai_key=api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        group_chat_id=int(group_id),
        initiative_enabled=os.getenv("INITIATIVE_ENABLED", "false").lower() == "true",
        initiative_interval_minutes=max(1, int(os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))),
        db_path=os.getenv("DB_PATH", db_default),
        system_prompt=prompts.get("system", ""),
        initiative_prompt=prompts.get("initiative", ""),
        google_docs_url=os.getenv("GOOGLE_DOCS_URL", "").strip(),
        knowledge_refresh_minutes=max(1, int(os.getenv("KNOWLEDGE_REFRESH_MINUTES", "10"))),
        knowledge_sources=os.getenv("KNOWLEDGE_SOURCES", "").strip() or "https://forum.comeback.pw",
    )


def save_local_settings(values: dict) -> None:
    lines = [f"{k}={str(v).replace(chr(10), ' ').replace(chr(13), ' ')}" for k, v in values.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)
