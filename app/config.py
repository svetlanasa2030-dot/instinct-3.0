from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

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


def load_settings() -> Settings:
    prompt_path = ROOT / "config" / "prompts.yaml"
    prompts = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    group_id = os.getenv("GROUP_CHAT_ID", "0").strip()
    if not token or not api_key or group_id == "0":
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN, OPENAI_API_KEY and GROUP_CHAT_ID")
    return Settings(
        telegram_token=token,
        openai_key=api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.1-mini"),
        group_chat_id=int(group_id),
        initiative_enabled=os.getenv("INITIATIVE_ENABLED", "false").lower() == "true",
        initiative_interval_minutes=max(1, int(os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))),
        db_path=os.getenv("DB_PATH", "data/bot.sqlite3"),
        system_prompt=prompts.get("system", ""),
        initiative_prompt=prompts.get("initiative", ""),
    )
