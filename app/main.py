import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.knowledge_ui import router as knowledge_router
from app.source_sync import collect_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

settings = load_settings()
storage = Storage(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
dp = Dispatcher()
dp.include_router(knowledge_router)

_bot_id: int | None = None
_polling_loop: asyncio.AbstractEventLoop | None = None
_polling_task: asyncio.Task | None = None
_knowledge_sync_task: asyncio.Task | None = None

_NAME_ADDRESS = re.compile(r'(?i)(?<!\w)алин(?:а|е|у|ой|ы)?(?!\w)')

def _addressed_to_alina(text: str) -> bool:
    return bool(_NAME_ADDRESS.search(text))


def _is_allowed_chat(message: Message) -> bool:
    return message.chat.id == settings.group_chat_id


@dp.message(F.text.startswith("/start"))
async def command_start(message: Message):
    if not _is_allowed_chat(message):
        return
    storage.set_chat_enabled(message.chat.id, True)
    await message.answer("🟢 Бот запущен. Теперь отвечаю на сообщения.")


@dp.message(F.text.startswith("/stop"))
async def command_stop(message: Message):
    if not _is_allowed_chat(message):
        return
    storage.set_chat_enabled(message.chat.id, False)
    await message.answer("🔴 Бот остановлен. Команду /start можно использовать для запуска.")


@dp.message(F.text.startswith("/status"))
async def command_status(message: Message):
    if not _is_allowed_chat(message):
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

    if text.split()[0].split("@")[0].lower() in {"/start", "/stop", "/status"}:
        return

    if not storage.is_chat_enabled(message.chat.id):
        logging.info("Bot is stopped for chat_id=%s; message ignored", message.chat.id)
        return

    # Reply to any message from Alina is also treated as a direct address,
    # so users can continue the conversation naturally without typing her name.
    is_reply_to_alina = False
    if message.reply_to_message is not None:
        replied_from = message.reply_to_message.from_user
        is_reply_to_alina = replied_from is not None and replied_from.id == _bot_id

    if not _addressed_to_alina(text) and not is_reply_to_alina:
        logging.info("Ignored message: no direct address to Alina and not a reply to her")
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



async def _sync_forum_forever():
    """Keep the configured forum/site index updated in the background."""
    global _knowledge_sync_task
    while True:
        try:
            sources = [x.strip() for x in settings.knowledge_sources.splitlines() if x.strip()]
            if sources:
                await asyncio.to_thread(collect_sources, sources, 20000)
                logging.info("Knowledge sources synchronized: %s", sources)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception("Knowledge synchronization failed: %s", exc)
        await asyncio.sleep(settings.knowledge_refresh_minutes * 60)


def request_stop():
    """Request polling shutdown from the GUI thread."""
    global _polling_loop, _polling_task
    if _polling_loop and _polling_task and not _polling_task.done():
        _polling_loop.call_soon_threadsafe(_polling_task.cancel)


async def main():
    global _bot_id, _polling_loop, _polling_task, _knowledge_sync_task

    _polling_loop = asyncio.get_running_loop()
    bot = Bot(settings.telegram_token)
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

    _knowledge_sync_task = asyncio.create_task(_sync_forum_forever())

    try:
        _polling_task = asyncio.current_task()
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        if _knowledge_sync_task and not _knowledge_sync_task.done():
            _knowledge_sync_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
