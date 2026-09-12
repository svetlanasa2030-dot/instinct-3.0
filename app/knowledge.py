from pathlib import Path
import re
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\wа-яА-ЯёЁ-]{2,}", text.lower())


def load_documents() -> list[tuple[str, str]]:
    docs = []
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    for path in KNOWLEDGE_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            docs.append((str(path.relative_to(KNOWLEDGE_DIR)), path.read_text(encoding="utf-8", errors="ignore")))
    return docs


def search_knowledge(query: str, limit: int = 5) -> str:
    query_words = Counter(_tokens(query))
    scored = []
    for name, text in load_documents():
        words = Counter(_tokens(text))
        score = sum(min(freq, words.get(word, 0)) for word, freq in query_words.items())
        if score > 0:
            scored.append((score, name, text))
    scored.sort(key=lambda item: item[0], reverse=True)
    chunks = []
    for _, name, text in scored[:limit]:
        chunks.append(f"Источник: {name}\n{text[:6000]}")
    return "\n\n---\n\n".join(chunks) if chunks else "Релевантной информации в базе знаний не найдено."
