import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.knowledge_ui import router as knowledge_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

settings = load_settings()
storage = Storage(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
bot = Bot(settings.telegram_token)
dp = Dispatcher()
dp.include_router(knowledge_router)

_bot_id: int | None = None


def _is_allowed_chat(message: Message) -> bool:
    return message.chat.id == settings.group_chat_id


def _is_admin_user(message: Message) -> bool:
    # Управление ботом разрешено владельцу/настроенному пользователю через ADMIN_USER_ID.
    # Если переменная не задана, команды /start, /stop, /status доступны для совместимости.
    admin_user_id = getattr(settings, "admin_user_id", None)
    if admin_user_id is None:
        return True
    return bool(message.from_user and message.from_user.id == admin_user_id)


@dp.message(F.text.startswith("/start"))
async def command_start(message: Message):
    if not _is_allowed_chat(message):
        return
    if not _is_admin_user(message):
        await message.answer("⛔ У тебя нет прав для управления ботом.")
        return

    storage.set_chat_enabled(message.chat.id, True)
    await message.answer("🟢 Бот запущен. Теперь отвечаю на сообщения.")


@dp.message(F.text.startswith("/stop"))
async def command_stop(message: Message):
    if not _is_allowed_chat(message):
        return
    if not _is_admin_user(message):
        await message.answer("⛔ У тебя нет прав для управления ботом.")
        return

    storage.set_chat_enabled(message.chat.id, False)
    await message.answer("🔴 Бот остановлен. Команду /start можно использовать для запуска.")


@dp.message(F.text.startswith("/status"))
async def command_status(message: Message):
    if not _is_allowed_chat(message):
        return
    if not _is_admin_user(message):
        await message.answer("⛔ У тебя нет прав для управления ботом.")
        return

    enabled = storage.is_chat_enabled(message.chat.id)
    status = "🟢 запущен" if enabled else "🔴 остановлен"
    await message.answer(f"Статус бота: {status}.")


@dp.message(F.text)
async def on_message(message: Message):
    global _bot_id

    logging.info(
        "Telegram message received: chat_id=%s from=%s text=%r",
        message.chat.id,
        message.from_user.id if message.from_user else None,
        message.text,
    )

    if not _is_allowed_chat(message):
        logging.info(
            "Ignored message: chat_id=%s, expected=%s",
            message.chat.id,
            settings.group_chat_id,
        )
        return

    text = (message.text or "").strip()
    if not text:
        return

    if _bot_id is not None and message.from_user and message.from_user.id == _bot_id:
        return

    # Команды управления обрабатываются отдельными handlers выше.
    if text.split()[0].split("@")[0].lower() in {"/start", "/stop", "/status"}:
        return

    # После /stop обычные сообщения полностью игнорируются.
    if not storage.is_chat_enabled(message.chat.id):
        logging.info("Bot is stopped for chat_id=%s; message ignored", message.chat.id)
        return

    username = message.from_user.username if message.from_user else None
    user_id = message.from_user.id if message.from_user else None
    storage.add(message.chat.id, user_id, username, "user", text)

    logging.info("Sending message to OpenAI: model=%s", ai.model)

    try:
        answer = await ai.decide_and_answer(message.chat.id, text)

        if not answer:
            logging.info("OpenAI returned NO_REPLY")
            return

        await message.answer(answer, reply_to_message_id=message.message_id)
        storage.add(message.chat.id, None, None, "assistant", answer)
        logging.info("Telegram reply sent successfully")

    except Exception as exc:
        logging.exception("Failed to generate/send answer: %s", exc)


async def main():
    global _bot_id

    me = await bot.get_me()
    _bot_id = me.id

    logging.info(
        "Telegram bot started: @%s | id=%s | can_read_all_group_messages=%s",
        me.username,
        me.id,
        me.can_read_all_group_messages,
    )

    if not me.can_read_all_group_messages:
        logging.warning(
            "Telegram Privacy Mode is enabled. "
            "The bot will NOT receive ordinary group messages. "
            "Disable Group Privacy in BotFather or make the bot an administrator."
        )

    await bot.delete_webhook(drop_pending_updates=False)

    logging.info(
        "Polling started. Waiting for messages in group %s",
        settings.group_chat_id,
    )

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
