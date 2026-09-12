import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .ai import AIEngine
from .config import load_settings
from .storage import Storage

logging.basicConfig(level=logging.INFO)

settings = load_settings()
storage = Storage(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
bot = Bot(settings.telegram_token)
dp = Dispatcher()

@dp.message(F.text)
async def on_message(message: Message):
    if message.chat.id != settings.group_chat_id:
        return
    text = (message.text or "").strip()
    if not text:
        return
    username = message.from_user.username if message.from_user else None
    user_id = message.from_user.id if message.from_user else None
    storage.add(message.chat.id, user_id, username, "user", text)

    # Reply to direct mentions/replies/questions; otherwise let the model decide if useful.
    should_answer = bool(message.reply_to_message) or f"@{(await bot.me()).username}" in text if await bot.me() else False
    if not should_answer and text.endswith("?"):
        should_answer = True
    if not should_answer:
        return

    try:
        answer = await ai.answer(message.chat.id, text)
        if answer:
            await message.answer(answer, reply_to_message_id=message.message_id)
            storage.add(message.chat.id, None, None, "assistant", answer)
    except Exception:
        logging.exception("Failed to generate answer")

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
        scheduler.add_job(
            send_initiative,
            "interval",
            minutes=settings.initiative_interval_minutes,
            id="group_initiative",
            replace_existing=True,
        )
        scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
