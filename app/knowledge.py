from pathlib import Path
import re
from collections import Counter
import urllib.request

from app.config import load_settings

_SETTINGS = load_settings()

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
GOOGLE_CACHE = Path(load_settings().db_path).parent / "google_knowledge.txt"

def _tokens(text: str) -> list[str]:
    return re.findall(r"[\wа-яА-ЯёЁ-]{2,}", text.lower())

def _google_export_url(url: str) -> str:
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    if not m:
        return ""
    return f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"

def refresh_google_doc(url: str) -> bool:
    export_url = _google_export_url(url)
    if not export_url:
        return False
    try:
        with urllib.request.urlopen(export_url, timeout=20) as response:
            text = response.read().decode("utf-8", errors="ignore")
        GOOGLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GOOGLE_CACHE.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False

def load_documents() -> list[tuple[str, str]]:
    docs = []
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    for path in KNOWLEDGE_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            docs.append((str(path.relative_to(KNOWLEDGE_DIR)), path.read_text(encoding="utf-8", errors="ignore")))
    if GOOGLE_CACHE.exists():
        docs.append(("Google Docs — база знаний", GOOGLE_CACHE.read_text(encoding="utf-8", errors="ignore")))
    return docs

def search_knowledge(query: str, limit: int = 5) -> str:
    # Перед ответом обновляем небольшую часть настроенных источников.
    # Это позволяет получать актуальную информацию только по запросу пользователя.
    try:
        sources = [x.strip() for x in _SETTINGS.knowledge_sources.splitlines() if x.strip()]
        if sources:
            from .source_sync import collect_sources
            collect_sources(sources, max_pages=10)
    except Exception:
        pass
    query_words = Counter(_tokens(query))
    scored = []
    for name, text in load_documents():
        words = Counter(_tokens(text))
        score = sum(min(freq, words.get(word, 0)) for word, freq in query_words.items())
        if score > 0:
            scored.append((score, name, text))
    scored.sort(key=lambda item: item[0], reverse=True)
    chunks = [f"Источник: {name}\n{text[:6000]}" for _, name, text in scored[:limit]]
    return "\n\n---\n\n".join(chunks) if chunks else "Релевантной информации в базе знаний не найдено."


def append_to_google_docs(webhook_url: str, url: str, text: str) -> bool:
    if not webhook_url:
        return False
    import json
    payload=json.dumps({"url":url,"text":text},ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(webhook_url,data=payload,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            return 200 <= response.status < 300
    except Exception:
        return False

def refresh_live_sources(query: str, max_pages: int = 6) -> None:
    """Fetch a small set of relevant pages from configured source sites before answering."""
    sources = [x.strip() for x in _SETTINGS.knowledge_sources.splitlines() if x.strip()]
    if not sources:
        return
    try:
        from .source_sync import collect_relevant_sources
        collect_relevant_sources(sources, query, max_pages=max_pages)
    except Exception:
        return
