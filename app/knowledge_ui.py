import asyncio
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from .knowledge_manager import list_documents, get_document, save_document, delete_document, normalize_filename
from .roles import is_telegram_admin

router = Router()


async def _is_admin(message: Message) -> bool:
    return bool(message.from_user) and await is_telegram_admin(message.bot, message.chat.id, message.from_user.id)

HELP = "📚 База знаний\\n\\n/knowledge — список материалов\\n/knowledge_add Название — добавить материал; следующим сообщением отправьте текст\\n/knowledge_get название — показать материал\\n/knowledge_delete название — удалить материал"

@router.message(Command("knowledge"))
async def knowledge(message: Message):
    if not await _is_admin(message):
        return
    docs = list_documents()
    await message.answer("📚 База знаний\\n\\n" + ("\\n".join("• " + x for x in docs) if docs else "Пока пуста.") + "\\n\\n" + HELP)

@router.message(Command("knowledge_get"))
async def knowledge_get(message: Message):
    if not await _is_admin(message):
        return
    name = (message.text or "").partition(" ")[2].strip()
    content = get_document(name) if name else None
    await message.answer(content[:10000] if content else "Материал не найден.")

@router.message(Command("knowledge_delete"))
async def knowledge_delete(message: Message):
    if not await _is_admin(message):
        return
    name = (message.text or "").partition(" ")[2].strip()
    await message.answer("Удалено." if name and delete_document(name) else "Материал не найден.")

_pending = {}

@router.message(Command("knowledge_add"))
async def knowledge_add(message: Message):
    if not await _is_admin(message):
        return
    title = (message.text or "").partition(" ")[2].strip()
    if not title:
        await message.answer("Использование: /knowledge_add Название")
        return
    _pending[message.from_user.id] = normalize_filename(title)
    await message.answer("Отправьте следующим сообщением текст материала. Он будет сохранён в базе знаний.")

@router.message(F.text)
async def capture_knowledge_text(message: Message):
    if not await _is_admin(message):
        return
    if not message.from_user or message.from_user.id not in _pending:
        return
    filename = _pending.pop(message.from_user.id)
    save_document(filename, message.text or "")
    await message.answer(f"✅ Материал сохранён: {filename}")
