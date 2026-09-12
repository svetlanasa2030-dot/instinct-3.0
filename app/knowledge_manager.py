from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"

ALLOWED = {".txt", ".md"}


def list_documents():
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    return sorted(str(p.relative_to(KNOWLEDGE_DIR)) for p in KNOWLEDGE_DIR.rglob("*") if p.is_file() and p.suffix.lower() in ALLOWED)


def get_document(name: str):
    path = _safe_path(name)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="ignore")


def save_document(name: str, content: str):
    path = _safe_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def delete_document(name: str):
    path = _safe_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def _safe_path(name: str) -> Path:
    name = name.strip().replace("\\\\", "/")
    if not name:
        raise ValueError("Имя материала не задано")
    path = (KNOWLEDGE_DIR / name).resolve()
    if KNOWLEDGE_DIR.resolve() not in path.parents:
        raise ValueError("Недопустимый путь")
    if path.suffix.lower() not in ALLOWED:
        path = path.with_suffix(".txt")
    return path


def normalize_filename(title: str):
    value = re.sub(r"[^\\wа-яА-ЯёЁ -]+", "", title, flags=re.UNICODE).strip()
    value = re.sub(r"\\s+", "_", value)
    return (value or "knowledge") + ".txt"
