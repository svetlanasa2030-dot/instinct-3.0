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


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openai_key: str
    openai_model: str
    gemini_key: str
    gemini_model: str
    ai_provider: str
    group_chat_id: int
    initiative_enabled: bool
    initiative_interval_minutes: int
    db_path: str
    system_prompt: str
    initiative_prompt: str
    google_docs_url: str
    knowledge_refresh_minutes: int


def load_settings() -> Settings:
    prompt_path = ROOT / "config" / "prompts.yaml"
    prompts = yaml.safe_load(prompt_path.read_text(encoding="utf-8")) or {}
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    group_id = os.getenv("GROUP_CHAT_ID", "0").strip()
    if not token or not api_key or group_id == "0":
        raise RuntimeError("Заполните Telegram Token, OpenAI API Key и Group Chat ID")
    db_default = str(APP_DATA / "bot.sqlite3")
    return Settings(
        telegram_token=token,
        openai_key=api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        gemini_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        ai_provider=os.getenv("AI_PROVIDER", "openai").strip().lower() or "openai",
        group_chat_id=int(group_id),
        initiative_enabled=os.getenv("INITIATIVE_ENABLED", "false").lower() == "true",
        initiative_interval_minutes=max(1, int(os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))),
        db_path=os.getenv("DB_PATH", db_default),
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or prompts.get("system", ""),
        initiative_prompt=os.getenv("INITIATIVE_PROMPT", "").strip() or prompts.get("initiative", ""),
        google_docs_url=os.getenv("GOOGLE_DOCS_URL", "").strip(),
        knowledge_refresh_minutes=max(1, int(os.getenv("KNOWLEDGE_REFRESH_MINUTES", "10"))),
    )


def save_local_settings(values: dict) -> None:
    lines = [f"{k}={str(v).replace(chr(10), ' ').replace(chr(13), ' ')}" for k, v in values.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)
