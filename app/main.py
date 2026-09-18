import asyncio
import logging
import re
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.knowledge_ui import router as knowledge_router
from app.source_sync import collect_sources
from app.game_features import init_game_features, add_watch, list_watches, remove_watch, check_watches
try:
    from app.news_monitor import run_news_monitor_in_thread
except ImportError:
    run_news_monitor_in_thread = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
settings = load_settings()
storage = Storage(settings.db_path)
init_game_features(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
dp = Dispatcher()
dp.include_router(knowledge_router)

_bot_id: int | None = None
_polling_loop: asyncio.AbstractEventLoop | None = None
_polling_task: asyncio.Task | None = None
_knowledge_sync_task: asyncio.Task | None = None
_news_monitor_thread = None
_watch_task: asyncio.Task | None = None
_NAME_ADDRESS = re.compile(r'(?i)(?<!\w)алин(?:а|е|у|ой|ы)?(?!\w)')


def _addressed_to_alina(text: str) -> bool: return bool(_NAME_ADDRESS.search(text))


def _strip_urls(text: str) -> str:
    text = re.sub(r'\[([^\]]+)\]\(\s*<?https?://[^)>]+>?\s*\)', r'\1', text)
    text = re.sub(r'<https?://[^>]+>', '', text)
    text = re.sub(r'\[\s*https?://[^\]]+\s*\]', '', text)
    text = re.sub(r'https?://[^\s)\]>]+', '', text, flags=re.I)
    text = re.sub(r'(?i)www\.[^\s)\]>]+', '', text)
    text = '\n'.join(line for line in text.splitlines() if not re.search(r'(?i)(https?://|www\.)', line))
    text = re.sub(r'!\[([^\]]*)\]\(\s*\)', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'\[\s*\]', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n[ \t]*\n[ \t]*\n+', '\n\n', text)
    return text.strip()


def _is_allowed_chat(message: Message) -> bool: return message.chat.id == settings.group_chat_id


def _parse_watch_command(text: str):
    body = re.sub(r'^/watch(?:@\w+)?\s*', '', text, flags=re.I).strip()
    if not body: return None, None
    match = re.search(r'\s+(?:до|дешевле|не дороже)\s+([\d\s.,]+)\s*$', body, re.I)
    if match:
        digits = re.sub(r'\D', '', match.group(1))
        return body[:match.start()].strip(), int(digits) if digits else None
    return body, None


@dp.message(F.text.startswith('/consultant'))
async def command_consultant(message: Message):
    if not _is_allowed_chat(message): return
    global _bot_id
    if _bot_id is None:
        await message.answer('ИИ-консультант пока не готов.')
        return
    bot = await message.bot.get_me()
    username = bot.username
    if not username:
        await message.answer('У бота нет username, поэтому не могу открыть Mini App.')
        return
    url = f"https://t.me/{username}?startapp=consultant"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🤖 Открыть ИИ-консультанта', url=url)
    ]])
    await message.answer('Откройте мой ИИ-консультант прямо внутри Telegram:', reply_markup=keyboard)


@dp.message(F.text.startswith('/start'))
async def command_start(message: Message):
    if not _is_allowed_chat(message): return
    storage.set_chat_enabled(message.chat.id, True)
    await message.answer('🟢 Бот запущен. Теперь отвечаю на сообщения.')


@dp.message(F.text.startswith('/stop'))
async def command_stop(message: Message):
    if not _is_allowed_chat(message): return
    storage.set_chat_enabled(message.chat.id, False)
    await message.answer('🔴 Бот остановлен. Команду /start можно использовать для запуска.')


@dp.message(F.text.startswith('/status'))
async def command_status(message: Message):
    if not _is_allowed_chat(message): return
    await message.answer(f"Статус бота: {'🟢 запущен' if storage.is_chat_enabled(message.chat.id) else '🔴 остановлен'}.")


@dp.message(F.text.startswith('/watch'))
async def command_watch(message: Message):
    if not _is_allowed_chat(message): return
    item, max_price = _parse_watch_command(message.text or '')
    if not item:
        await message.answer('Формат: /watch предмет [до 4 000 000]')
        return
    watch_id = add_watch(settings.db_path, message.chat.id, message.from_user.id if message.from_user else None, item, max_price)
    limit = f" до {max_price:,}".replace(',', ' ') if max_price else ''
    await message.answer(f'🔔 Поставила на контроль №{watch_id}: {item}{limit}\nПроверяю котобазу каждые 15 минут.')


@dp.message(F.text.startswith('/watches'))
async def command_watches(message: Message):
    if not _is_allowed_chat(message): return
    rows = list_watches(settings.db_path, message.chat.id)
    if not rows:
        await message.answer('Активных наблюдений нет.')
        return
    lines = ['🔔 Наблюдения:']
    for watch_id, item, max_price in rows:
        limit = f" ≤ {max_price:,}".replace(',', ' ') if max_price else ''
        lines.append(f'#{watch_id} — {item}{limit}')
    lines.append('\nУдалить: /unwatch ID')
    await message.answer('\n'.join(lines))


@dp.message(F.text.startswith('/unwatch'))
async def command_unwatch(message: Message):
    if not _is_allowed_chat(message): return
    match = re.search(r'^/unwatch(?:@\w+)?\s+(\d+)', message.text or '', re.I)
    if not match:
        await message.answer('Формат: /unwatch ID')
        return
    ok = remove_watch(settings.db_path, message.chat.id, int(match.group(1)))
    await message.answer('🗑 Наблюдение удалено.' if ok else 'Не нашла такое наблюдение.')


@dp.message(F.text.startswith('/history'))
async def command_history(message: Message):
    if not _is_allowed_chat(message): return
    item = re.sub(r'^/history(?:@\\w+)?\\s*', '', message.text or '', flags=re.I).strip()
    if not item:
        await message.answer('Формат: /history предмет')
        return
    from app.game_features import price_analysis
    await message.answer(price_analysis(settings.db_path, message.chat.id, item))


@dp.message(F.text.startswith('/market'))
async def command_market(message: Message):
    if not _is_allowed_chat(message): return
    from app.game_features import market_summary
    await message.answer(market_summary(settings.db_path, message.chat.id))


@dp.message(F.text)
async def on_message(message: Message):
    global _bot_id
    if not _is_allowed_chat(message): return
    original_text = (message.text or '').strip()
    if not original_text: return
    if _bot_id is not None and message.from_user and message.from_user.id == _bot_id: return
    if original_text.split()[0].split('@')[0].lower() in {'/start','/stop','/status','/consultant','/watch','/watches','/unwatch','/history','/market'}: return
    if not storage.is_chat_enabled(message.chat.id): return
    is_reply_to_alina = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == _bot_id)
    if not _addressed_to_alina(original_text) and not is_reply_to_alina: return

    text = original_text
    storage.add(message.chat.id, message.from_user.id if message.from_user else None, message.from_user.username if message.from_user else None, 'user', text)
    try:
        answer = _strip_urls(await ai.decide_and_answer(message.chat.id, text))
        if not answer: return
        await message.answer(answer, reply_to_message_id=message.message_id)
        storage.add(message.chat.id, None, None, 'assistant', answer)
    except Exception as exc:
        logging.exception('Failed to generate/send answer: %s', exc)


async def _sync_forum_forever():
    while True:
        try:
            sources = [x.strip() for x in settings.knowledge_sources.splitlines() if x.strip()]
            if sources: await asyncio.to_thread(collect_sources, sources, 20000)
        except asyncio.CancelledError: raise
        except Exception as exc: logging.exception('Knowledge synchronization failed: %s', exc)
        await asyncio.sleep(settings.knowledge_refresh_minutes * 60)


async def _watch_forever(bot: Bot):
    loop = asyncio.get_running_loop()
    def send_message(chat_id, text):
        future = asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text), loop)
        future.result(timeout=30)
    while True:
        try:
            await asyncio.to_thread(check_watches, settings.db_path, send_message)
        except asyncio.CancelledError: raise
        except Exception as exc: logging.exception('Watch synchronization failed: %s', exc)
        await asyncio.sleep(15 * 60)


def request_stop():
    global _polling_loop, _polling_task
    if _polling_loop and _polling_task and not _polling_task.done(): _polling_loop.call_soon_threadsafe(_polling_task.cancel)


async def main():
    global _bot_id, _polling_loop, _polling_task, _knowledge_sync_task, _news_monitor_thread, _watch_task
    _polling_loop = asyncio.get_running_loop()
    bot = Bot(settings.telegram_token)
    me = await bot.get_me()
    _bot_id = me.id
    await bot.delete_webhook(drop_pending_updates=False)
    _knowledge_sync_task = asyncio.create_task(_sync_forum_forever())
    _watch_task = asyncio.create_task(_watch_forever(bot))
    if run_news_monitor_in_thread is not None:
        import threading
        _news_monitor_thread = threading.Thread(target=run_news_monitor_in_thread, name='telegram-news-monitor', daemon=True)
        _news_monitor_thread.start()
    try:
        _polling_task = asyncio.current_task()
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in (_knowledge_sync_task, _watch_task):
            if task and not task.done(): task.cancel()
        await bot.session.close()


if __name__ == '__main__': asyncio.run(main())
