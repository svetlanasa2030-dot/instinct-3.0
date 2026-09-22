import asyncio
import logging
import re
import random
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReactionTypeEmoji

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.reminders import ReminderService, is_authorized, parse_command
from app.knowledge_ui import router as knowledge_router
from app.source_sync import collect_sources
from app.game_features import init_game_features, add_watch, list_watches, remove_watch, check_watches
from app.forum_search import search_forum
from app.youtube_monitor import monitor_forever
try:
    from app.news_monitor import run_news_monitor_in_thread
except ImportError:
    run_news_monitor_in_thread = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
settings = load_settings()
storage = Storage(settings.db_path)
init_game_features(settings.db_path)
ai = AIEngine(settings.openai_key, settings.openai_model, settings.system_prompt, storage)
reminder_service = ReminderService(settings.db_path)
dp = Dispatcher()
dp.include_router(knowledge_router)

_bot_id: int | None = None
_polling_loop: asyncio.AbstractEventLoop | None = None
_polling_task: asyncio.Task | None = None
_knowledge_sync_task: asyncio.Task | None = None
_news_monitor_thread = None
_watch_task: asyncio.Task | None = None
_reminder_task: asyncio.Task | None = None
_youtube_task: asyncio.Task | None = None
_random_events_task: asyncio.Task | None = None
_morning_greeting_task: asyncio.Task | None = None
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




@dp.message(F.text, lambda message: is_authorized(message.from_user.username if message.from_user else None) and parse_command((message.text or '').strip()) is not None)
async def command_reminder(message: Message):
    if not _is_allowed_chat(message):
        return
    username = message.from_user.username if message.from_user else None
    if not is_authorized(username):
        return

    parsed = parse_command((message.text or "").strip())
    if not parsed:
        return

    run_at, reminder_text = parsed
    reminder_id = reminder_service.schedule(
        message.chat.id,
        message.from_user.id if message.from_user else None,
        username,
        reminder_text,
        run_at,
    )
    when = run_at.strftime("%d.%m.%Y в %H:%M")
    await message.answer(f"⏰ Готово. Напомню {when}: {reminder_text} (№{reminder_id})")




def _authorized_reminder_user(message: Message) -> bool:
    return _is_allowed_chat(message) and is_authorized(message.from_user.username if message.from_user else None)


@dp.message(F.text.startswith('/reminders'))
async def command_reminders(message: Message):
    if not _authorized_reminder_user(message):
        return
    rows = reminder_service.list_pending(message.chat.id)
    if not rows:
        await message.answer('📭 Активных напоминаний нет.')
        return
    lines = ['⏰ Активные напоминания:']
    for reminder_id, text, run_at, repeat_rule in rows:
        dt = datetime.fromisoformat(run_at).astimezone()
        lines.append(f'#{reminder_id} — {dt.strftime("%d.%m.%Y %H:%M")} — {text}')
    lines.append('Отменить: /cancel ID')
    await message.answer('\n'.join(lines))


@dp.message(F.text.startswith('/cancel'))
async def command_cancel(message: Message):
    if not _authorized_reminder_user(message):
        return
    match = re.search(r'^/cancel(?:@\w+)?\s+(\d+)', message.text or '', re.I)
    if not match:
        await message.answer('Формат: /cancel ID')
        return
    ok = reminder_service.cancel(message.chat.id, int(match.group(1)))
    await message.answer('🗑 Напоминание отменено.' if ok else 'Не нашла такое напоминание.')



def _parse_forum_search(text: str):
    body = re.sub(r'(?i)^\s*алина[,:]?\s*', '', text).strip()
    match = re.match(r'(?is)^(?:поищи|найди|ищи|посмотри|проверь)\s+(?:на\s+)?форум(?:е|а)?\s+(.+)$', body)
    if not match:
        return None
    query = match.group(1).strip()
    query = re.sub(r'(?i)\b(?:на\s+)?форуме\b', '', query).strip(' ,:')
    return query or None


@dp.message(F.text, lambda message: _is_allowed_chat(message) and is_authorized(message.from_user.username if message.from_user else None) and _parse_forum_search((message.text or '').strip()) is not None)
async def command_forum_search(message: Message):
    username = message.from_user.username if message.from_user else None
    if not is_authorized(username):
        return
    query = _parse_forum_search((message.text or '').strip())
    if not query:
        return
    sources = [x.strip() for x in settings.knowledge_sources.splitlines() if x.strip()]
    forum_url = next((x for x in sources if 'forum' in x.lower()), sources[0] if sources else '')
    if not forum_url:
        await message.answer('Не настроен адрес форума.')
        return
    try:
        result = await asyncio.to_thread(search_forum, forum_url, query, 7)
        if not result:
            await message.answer(f'🔎 По запросу «{query}» на форуме ничего не нашла.')
            return
        await message.answer(f'🔎 Нашла на форуме по запросу «{query}»:\n\n{result}')
    except Exception as exc:
        logging.exception('Forum search failed: %s', exc)
        await message.answer('Не смогла выполнить поиск по форуму. Попробуй ещё раз.')



def _game_request(text: str) -> bool:
    normalized = re.sub(r'[^a-zа-яё0-9 ]+', ' ', text.lower())
    normalized = re.sub(r'\\s+', ' ', normalized).strip()
    return bool(re.search(r'\\bалина\\b', normalized) and re.search(r'\\bдавай\\s+(?:поиграем|играть)\\b', normalized))


@dp.message(F.text, lambda message: _is_allowed_chat(message) and _game_request((message.text or '').strip()))
async def command_game(message: Message):
    if not _is_allowed_chat(message):
        return
    import random
    games = [
        ('💋 «Правда или провокация»', 'Пишем «Я» — я выберу участников и начнём.'),
        ('😈 «Самый наглый»', 'Я даю ситуацию, а вы пишете самый дерзкий ответ. Победителя выберу я.'),
        ('🔥 «Кому бы ты…»', 'Я задаю провокационные вопросы про участников чата. Отвечаем честно 😏'),
        ('🍷 «Свидание вслепую»', 'Я случайно объединю двух участников и устрою им мини-свидание.'),
        ('😏 «Продолжи фразу»', 'Я начинаю фразу, а вы заканчиваете её. Чем смешнее и смелее — тем лучше.'),
        ('😂 «Кто из нас?»', 'Я задаю вопросы вроде «кто первым влюбится?» — а вы выбираете игрока.'),
    ]
    title, rules = random.choice(games)
    await message.answer(
        f'😈 Ну что, начинаем?\\n\\n'
        f'Сегодня я выбрала {title}.\\n\\n'
        f'{rules}\\n\\n'
        f'Кто участвует — пишите «Я» 👀'
    )


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


@dp.message(F.text.startswith('/remember'))
async def command_remember(message: Message):
    if not _is_allowed_chat(message): return
    memory = re.sub(r'^/remember(?:@\\w+)?\\s*', '', message.text or '', flags=re.I).strip()
    if not memory:
        await message.answer('Формат: /remember событие, мем или важный факт клана')
        return
    storage.add_clan_memory(message.chat.id, memory)
    await message.answer('🧠 Запомнила. Это теперь часть клановой памяти.')


@dp.message(F.text.startswith('/memories'))
async def command_memories(message: Message):
    if not _is_allowed_chat(message): return
    rows = storage.clan_memories(message.chat.id, 10)
    if not rows:
        await message.answer('🧠 Клановая память пока пустая.')
        return
    lines = ['🧠 Последние записи клановой памяти:']
    for memory_id, memory, _ in rows:
        lines.append(f'#{memory_id} — {memory}')
    await message.answer('\n'.join(lines))


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
    if original_text.split()[0].split('@')[0].lower() in {'/start','/stop','/status','/consultant','/watch','/watches','/unwatch','/history','/market','/reminders','/cancel'}: return
    if not storage.is_chat_enabled(message.chat.id): return
    is_reply_to_alina = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == _bot_id)
    display_name = message.from_user.full_name if message.from_user else None
    user_id = message.from_user.id if message.from_user else None
    previous_seen = storage.user_last_seen(message.chat.id, user_id) if user_id else None
    storage.remember_user(message.chat.id, user_id, message.from_user.username if message.from_user else None, display_name, original_text)

    # Алина замечает возвращение участника после долгого отсутствия.
    if previous_seen and user_id:
        try:
            last_seen_dt = datetime.fromisoformat(previous_seen)
            if last_seen_dt.tzinfo is None:
                last_seen_dt = last_seen_dt.replace(tzinfo=__import__('datetime').timezone.utc)
            hours_away = (datetime.now(__import__('datetime').timezone.utc) - last_seen_dt).total_seconds() / 3600
            if hours_away >= 24:
                return_name = display_name or (f'@{message.from_user.username}' if message.from_user and message.from_user.username else 'ты')
                return_messages = [
                    f'О, {return_name} воскресла 😏 Я уже думала, куда ты пропала.',
                    f'О, {return_name} вернулась 👀 А я уже заметила, что тебя давно не было.',
                    f'Наконец-то {return_name} объявилась 😌 Я тебя уже потеряла.',
                    f'О, {return_name} снова с нами 😏 Где пропадала?',
                ]
                await message.answer(random.choice(return_messages))
        except (ValueError, TypeError, OverflowError):
            pass

    if not _addressed_to_alina(original_text) and not is_reply_to_alina: return

    text = original_text
    # Иногда Алина реагирует на сообщение прямо в Telegram, без отдельного текста.
    # Это делает реакцию естественной и не превращает каждый ответ в спам реакциями.
    if random.random() < 0.35:
        try:
            await message.react(reaction=[ReactionTypeEmoji(emoji=random.choice(['👍', '❤️', '😂', '🔥', '👀']))])
        except Exception as exc:
            logging.debug('Could not add Telegram reaction: %s', exc)

    storage.add(message.chat.id, message.from_user.id if message.from_user else None, message.from_user.username if message.from_user else None, 'user', text)
    try:
        answer = _strip_urls(await ai.decide_and_answer(message.chat.id, text))
        if not answer: return
        await message.answer(answer, reply_to_message_id=message.message_id)
        storage.add(message.chat.id, None, None, 'assistant', answer)
    except Exception as exc:
        logging.exception('Failed to generate/send answer: %s', exc)




async def _reminders_forever(bot: Bot):
    loop = asyncio.get_running_loop()

    def send_message(chat_id, text):
        future = asyncio.run_coroutine_threadsafe(bot.send_message(chat_id, text), loop)
        future.result(timeout=30)

    while True:
        try:
            await asyncio.to_thread(reminder_service.send_due, send_message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception('Reminder delivery failed: %s', exc)
        await asyncio.sleep(5)


async def _morning_greeting_forever(bot: Bot):
    """Каждое утро около 10:00 Алина сама здоровается с кланом."""
    while True:
        now = datetime.now().astimezone()
        target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= target:
            target += __import__('datetime').timedelta(days=1)
        await asyncio.sleep(max(1, (target - datetime.now().astimezone()).total_seconds()))
        try:
            greetings = [
                'Всем привет! ☀️',
                'Всем доброе утро 😊',
                'Доброе утро, народ! 👋',
                'Всем привет! Ну что, просыпаемся? 😌',
                'Доброе утро, клан 🌞',
            ]
            await bot.send_message(settings.group_chat_id, random.choice(greetings), message_thread_id=2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.exception('Morning greeting failed: %s', exc)


async def _youtube_forever(bot: Bot):
    loop = asyncio.get_running_loop()

    def send_message(text):
        future = asyncio.run_coroutine_threadsafe(
            bot.send_message(settings.group_chat_id, text, message_thread_id=2), loop
        )
        future.result(timeout=30)

    await asyncio.to_thread(monitor_forever, settings.db_path, send_message)


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
    global _bot_id, _polling_loop, _polling_task, _knowledge_sync_task, _news_monitor_thread, _watch_task, _reminder_task, _youtube_task, _morning_greeting_task
    _polling_loop = asyncio.get_running_loop()
    bot = Bot(settings.telegram_token)
    me = await bot.get_me()
    _bot_id = me.id
    await bot.delete_webhook(drop_pending_updates=False)
    _knowledge_sync_task = asyncio.create_task(_sync_forum_forever())
    _watch_task = asyncio.create_task(_watch_forever(bot))
    _reminder_task = asyncio.create_task(_reminders_forever(bot))
    _youtube_task = asyncio.create_task(_youtube_forever(bot))
    _morning_greeting_task = asyncio.create_task(_morning_greeting_forever(bot))
    if run_news_monitor_in_thread is not None:
        import threading
        _news_monitor_thread = threading.Thread(target=run_news_monitor_in_thread, name='telegram-news-monitor', daemon=True)
        _news_monitor_thread.start()
    try:
        _polling_task = asyncio.current_task()
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in (_knowledge_sync_task, _watch_task, _reminder_task, _youtube_task, _morning_greeting_task):
            if task and not task.done(): task.cancel()
        await bot.session.close()


if __name__ == '__main__': asyncio.run(main())
