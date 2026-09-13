import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.knowledge_ui import router as knowledge_router

logging.basicConfig(level=logging.INFO)

settings = load_settings()
storage = Storage(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
bot = Bot(settings.telegram_token)
dp = Dispatcher()
dp.include_router(knowledge_router)

@dp.message(F.text)
async def on_message(message: Message):
    if message.chat.id != settings.group_chat_id:
        return
    text = (message.text or "").strip()
    if not text:
        return
    # Не обрабатываем собственные сообщения бота.
    me = await bot.me()
    if message.from_user and me and message.from_user.id == me.id:
        return

    username = message.from_user.username if message.from_user else None
    user_id = message.from_user.id if message.from_user else None
    storage.add(message.chat.id, user_id, username, "user", text)

    # Бот читает каждое сообщение группы и перед ответом сам решает
    # по основному промту, есть ли повод вступить в разговор.
    try:
        answer = await ai.decide_and_answer(message.chat.id, text)
        if answer:
            await message.answer(answer, reply_to_message_id=message.message_id)
            storage.add(message.chat.id, None, None, "assistant", answer)
    except Exception as exc:
        logging.exception("Failed to generate answer")
        logging.error("AI provider=%s model=%s error=%s", ai.provider, ai.model, exc)

async def send_initiative():
    if not settings.initiative_enabled:
        return
    try:
        text = await ai.initiative(settings.group_chat_id, settings.initiative_prompt)
        if text:
            await bot.send_message(settings.group_chat_id, text)
            storage.add(settings.group_chat_id, None, None, "assistant", text)
    except Exception:
        logging.exception("Failed to send initiative message")

async def main():
    scheduler = AsyncIOScheduler()
    if settings.initiative_enabled:
        scheduler.add_job(send_initiative, "interval", minutes=settings.initiative_interval_minutes, id="group_initiative", replace_existing=True)
        scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
