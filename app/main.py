import asyncio
import logging
import re
import random
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReactionTypeEmoji

from app.ai import AIEngine
from app.config import load_settings
from app.storage import Storage
from app.reminders import ReminderService, is_authorized, parse_command
from app.knowledge_ui import router as knowledge_router
from app.source_sync import collect_sources
from app.game_features import init_game_features, add_watch, list_watches, remove_watch, check_watches
from app.forum_search import search_forum
from app.youtube_monitor import monitor_forever, _latest_video
from app.youtube_browser import like_video, get_video_rating
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
_newbie_sessions: dict[int, dict] = {}
_NEWBIE_YES = {"да", "д", "yes", "y", "конечно"}
_NEWBIE_NO = {"нет", "н", "no", "n"}

# Google Sheets integration for accepted recruits.
GOOGLE_SHEETS_WEBHOOK = "https://script.google.com/macros/s/AKfycbzdId2N2sJ3HyNb_K5JeAU4Im7ib8G6nOgR5k2ghmm2f-77-3x2V6xCPY6X7i1GRMtMIg/exec"
GOOGLE_SHEETS_SECRET = "AKfycbzdId2N2sJ3HyNb_K5JeAU4Im7ib8G6nOgR5k2ghmm2f-77-3x2V6xCPY6X7i1GRMtMIg"

_NAME_ADDRESS = re.compile(r'(?i)(?<!\w)алин(?:а|е|у|ой|ы)?(?!\w)')


def _addressed_to_alina(text: str) -> bool: return bool(_NAME_ADDRESS.search(text))


async def _send_recruit_to_google_sheets(
    data: dict,
    added_by_username: str | None,
    added_by_display_name: str,
):
    """Отправляет принятого новичка в Google Sheets через Apps Script."""
    payload = {
        "secret": GOOGLE_SHEETS_SECRET,
        "date": datetime.now().astimezone().isoformat(),
        "game_nickname": data.get("game_nickname", ""),
        "level": data.get("level", ""),
        "class_name": data.get("class_name", ""),
        "teamspeak": data.get("teamspeak", ""),
        "telegram": data.get("telegram", ""),
        "added_by": (
            f"@{added_by_username}"
            if added_by_username
            else added_by_display_name
        ),
    }

    class _PreservePostRedirect(urllib.request.HTTPRedirectHandler):
        """Google Apps Script часто отвечает редиректом; сохраняем POST при переходе."""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if code in (301, 302, 303, 307, 308) and req.data is not None:
                return urllib.request.Request(
                    newurl,
                    data=req.data,
                    headers=dict(req.header_items()),
                    origin_req_host=req.origin_req_host,
                    unverifiable=True,
                    method="POST",
                )
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    def _post():
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            GOOGLE_SHEETS_WEBHOOK,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_PreservePostRedirect())
        try:
            with opener.open(request, timeout=20) as response:
                result = response.read().decode("utf-8", errors="replace")
                logging.info(
                    "[GOOGLE SHEETS] HTTP %s, final_url=%s, body=%s",
                    response.status,
                    response.geturl(),
                    result[:1000],
                )
                return response.status, result
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logging.error(
                "[GOOGLE SHEETS] HTTP ERROR %s, url=%s, body=%s",
                exc.code,
                exc.geturl(),
                error_body[:2000],
            )
            raise

    try:
        status, result = await asyncio.to_thread(_post)
        try:
            response_data = json.loads(result)
        except json.JSONDecodeError:
            response_data = {}

        if status != 200 or response_data.get("ok") is False:
            logging.error(
                "[GOOGLE SHEETS] Apps Script rejected recruit: status=%s response=%s",
                status,
                result[:2000],
            )
            return False

        logging.info("[GOOGLE SHEETS] Recruit synced successfully: %s", result)
        return True
    except Exception:
        logging.exception("[GOOGLE SHEETS] Failed to sync recruit")
        return False


def _is_knowledge_correction(text: str) -> bool:
    normalized = text.lower().strip()
    markers = (
        "ты ошиблась", "ты ошибся", "это неверно", "это неправильно",
        "неправильно", "ошибка", "исправь", "исправление", "на самом деле",
        "правильно будет", "правильный ответ", "не так", "не верно",
    )
    has_marker = any(marker in normalized for marker in markers)
    has_contrast = bool(re.search(r"\\bне\\b.{0,120}\\bа\\b", normalized, re.S))
    return has_marker or has_contrast


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


async def _close_newbie_session(callback: CallbackQuery, notice: str | None = None):
    user_id = callback.from_user.id
    if callback.message is None:
        return
    chat_id = callback.message.chat.id
    message_ids = storage.get_newbie_message_ids(chat_id, user_id)
    ids = set(storage.get_newbie_messages(chat_id, user_id))
    ids.add(callback.message.message_id)
    if message_ids:
        ids.update(x for x in message_ids if x)

    _newbie_sessions.pop(user_id, None)
    storage.delete_newbie_draft(chat_id, user_id)
    storage.delete_newbie_message_ids(chat_id, user_id)
    storage.delete_newbie_messages(chat_id, user_id)

    for message_id in ids:
        try:
            await callback.bot.delete_message(chat_id, message_id)
        except Exception as exc:
            logging.warning("Could not delete newbie message %s: %s", message_id, exc)

    if notice:
        await callback.answer(notice)


@dp.callback_query(F.data == "newbie_cancel")
async def newbie_cancel_callback(callback: CallbackQuery):
    await _close_newbie_session(callback, "Анкета отменена")


@dp.callback_query(F.data == "newbie_reject")
async def newbie_reject_callback(callback: CallbackQuery):
    await _close_newbie_session(callback, "Анкета отклонена")


@dp.callback_query(F.data == "newbie_restart")
async def newbie_restart_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    await _close_newbie_session(callback, "Заполняем заново")
    _newbie_sessions[user_id] = {"chat_id": chat_id, "step": "form", "data": {}}
    storage.save_newbie_draft(chat_id, user_id, {})
    prompt_message = await callback.message.answer(
        "📝 <b>Анкета новичка</b>\n\n"
        "🎮 Игровой ник:\n"
        "⭐ Уровень:\n"
        "⚔️ Класс:\n"
        "🎧 TeamSpeak: Да / Нет\n"
        "📱 Telegram: Да / Нет\n\n"
        "Отправь <b>одним сообщением через запятую</b> в таком порядке:\n"
        "<code>ИгровойНик, 146, Син, Да, Да</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отменить", callback_data="newbie_cancel"),
        ]]),
        parse_mode="HTML",
    )
    _newbie_sessions[user_id]["questionnaire_message_id"] = prompt_message.message_id
    storage.save_newbie_message_ids(chat_id, user_id, questionnaire_message_id=prompt_message.message_id)


@dp.message(
    F.text,
    lambda message: _is_allowed_chat(message)
    and re.sub(r'[,:!?]+', ' ', (message.text or '').strip()).strip().lower()
    in {'алина', 'алина привет', 'алина ты тут', 'алина ты здесь', 'алина ау', 'алина ало', 'алина откликнись'}
)
async def direct_alina_ping(message: Message):
    """Быстрый ответ на простые обращения, не зависящий от ИИ."""
    await message.answer("Да, я здесь 🙂", reply_to_message_id=message.message_id)


def _is_youtube_question(text: str) -> bool:
    normalized = text.lower()
    return (
        ("ютуб" in normalized or "youtube" in normalized or "k4mui" in normalized)
        and ("лайк" in normalized or "видео" in normalized or "ролик" in normalized)
        and ("провер" in normalized or "точно" in normalized or "постав" in normalized or "лайкнула" in normalized or "лайкнул" in normalized)
    )


async def _youtube_status_answer() -> str:
    latest = await asyncio.to_thread(_latest_video)
    if not latest:
        return "Не смогла проверить последний ролик @k4mui_play."
    video_id, title, url, _published = latest
    rating = await asyncio.to_thread(get_video_rating, video_id)
    if rating == "like":
        return f"Да 😌 Проверила — на последнем ролике «{title}» лайк от моего аккаунта уже стоит."
    if rating == "dislike":
        return f"Проверила 👀 На последнем ролике «{title}» сейчас стоит дизлайк."
    if rating == "none":
        return f"Проверила — на последнем ролике «{title}» лайка от моего аккаунта сейчас нет."
    return f"Проверила — YouTube не показывает, что мой аккаунт поставил лайк на «{title}»."




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



def _newbie_prompt(message: Message) -> str:
    return (
        "📝 Заполняем новичка. Я задам несколько вопросов.\n\n"
        "1️⃣ Игровой ник:"
    )


def _normalize_username(username: str | None) -> str:
    return (username or "").strip().lstrip("@").lower()


def _parse_recruiter_query(text: str):
    normalized = text.strip()
    # «Кого я принял/приняла?» — это запрос самого отправителя.
    if re.search(r"(?iu)\bкого\s+я\s+(?:принял|приняла|принимал|принимала|внёс|внесла|записал|записала)\b", normalized):
        return "__SELF__"
    match = re.search(
        r"(?iu)\bкого\s+(?:ты\s+)?(?:принял|приняла|приняли|принимал|принимала|принимали|внёс|внес|внесла|внесли|записал|записала|записали)\s+@?([a-z0-9_]+)",
        normalized,
    )
    if match:
        return match.group(1)
    return None


@dp.message(
    F.text,
    lambda message: (
        _is_allowed_chat(message)
        and _addressed_to_alina((message.text or "").strip())
        and _parse_recruiter_query((message.text or "").strip()) is not None
    ),
)
async def recruiter_history_query(message: Message):
    # История рекрутирования всегда обрабатывается отдельно от /newbie.
    await command_recruiter_list(message)


@dp.message(Command('newbie'))
async def command_newbie(message: Message):
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return
    _newbie_sessions[user_id] = {
        "chat_id": message.chat.id,
        "step": "form",
        "data": {},
    }
    storage.save_newbie_draft(message.chat.id, user_id, {})
    prompt_message = await message.answer(
        "📝 <b>Анкета новичка</b>\n\n"
        "🎮 Игровой ник:\n"
        "⭐ Уровень:\n"
        "⚔️ Класс:\n"
        "🎧 TeamSpeak: Да / Нет\n"
        "📱 Telegram: Да / Нет\n\n"
        "Отправь <b>одним сообщением через запятую</b> в таком порядке:\n"
        "<code>ИгровойНик, 146, Син, Да, Да</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚫 Отменить", callback_data="newbie_cancel"),
        ]]),
        parse_mode="HTML",
    )
    _newbie_sessions[user_id]["questionnaire_message_id"] = prompt_message.message_id
    storage.save_newbie_message_ids(message.chat.id, user_id, questionnaire_message_id=prompt_message.message_id)
    storage.add_newbie_message(message.chat.id, user_id, prompt_message.message_id)


@dp.message(
    F.text,
    lambda message: bool(message.from_user and message.from_user.id in _newbie_sessions)
    and not (
        _is_allowed_chat(message)
        and _addressed_to_alina((message.text or "").strip())
        and _parse_recruiter_query((message.text or "").strip()) is not None
    ),
)
async def newbie_form_message(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()

    # Запрос истории всегда имеет приоритет над активной анкетой.
    recruiter = _parse_recruiter_query(text)
    if _is_allowed_chat(message) and _addressed_to_alina(text) and recruiter:
        await command_recruiter_list(message)
        return

    session = _newbie_sessions.get(user_id)
    if not session or session["chat_id"] != message.chat.id:
        draft = storage.get_newbie_draft(message.chat.id, user_id)
        if draft:
            session = {"chat_id": message.chat.id, "step": "form", "data": draft}
            _newbie_sessions[user_id] = session
        else:
            return

    if text.lower().startswith("/newbie"):
        session["step"] = "form"
        session["data"] = {}
        storage.save_newbie_draft(message.chat.id, user_id, {})
        await message.answer(
            "📝 <b>Анкета новичка</b>\n\n"
            "🎮 Игровой ник:\n"
            "⭐ Уровень:\n"
            "⚔️ Класс:\n"
            "🎧 TeamSpeak: Да / Нет\n"
            "📱 Telegram: Да / Нет\n\n"
            "Отправь <b>одним сообщением через запятую</b> в таком порядке:\n"
            "<code>ИгровойНик, 146, Син, Да, Да</code>",
            parse_mode="HTML",
        )
        return

    if session.get("step") == "confirm":
        # Пока пользователь не нажал «Принять» или «Отклонить»,
        # не продолжаем анкету и не отдаём сообщение другим обработчикам.
        data = session.get("data") or storage.get_newbie_draft(message.chat.id, user_id)
        if data and data.get("game_nickname"):
            reminder_message = await message.answer(
                "📋 <b>Анкета ожидает решения.</b>\n\n"
                "Принять анкету или отклонить?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Принять", callback_data="newbie_confirm"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data="newbie_reject"),
                    InlineKeyboardButton(text="🚫 Отменить", callback_data="newbie_cancel"),
                ]]),
                parse_mode="HTML",
            )
            storage.add_newbie_message(message.chat.id, user_id, reminder_message.message_id)
            return

    # Анкету заполняем одним сообщением через запятую:
    # Игровой ник, уровень, класс, TeamSpeak, Telegram
    fields = [part.strip() for part in text.split(",")]
    if len(fields) != 5:
        await message.answer(
            "⚠️ Отправь анкету одним сообщением через запятую:\n\n"
            "<code>Малком, 100, Син, Да, Да</code>\n\n"
            "Порядок: игровой ник, уровень, класс, TeamSpeak, Telegram.",
            parse_mode="HTML",
        )
        return

    teamspeak = fields[3].lower()
    telegram = fields[4].lower()
    if teamspeak not in _NEWBIE_YES | _NEWBIE_NO or telegram not in _NEWBIE_YES | _NEWBIE_NO:
        await message.answer("⚠️ В строках TeamSpeak и Telegram укажи только «Да» или «Нет».")
        return

    data = {
        "game_nickname": fields[0][:100],
        "level": fields[1][:50],
        "class_name": fields[2][:100],
        "teamspeak": "Да" if teamspeak in _NEWBIE_YES else "Нет",
        "telegram": "Да" if telegram in _NEWBIE_YES else "Нет",
    }
    storage.save_newbie_draft(message.chat.id, user_id, data)
    session["data"] = data
    session["step"] = "confirm"

    confirmation_message = await message.answer(
        "📋 <b>Проверь анкету:</b>\n\n"
        f"🎮 Игровой ник: {data['game_nickname']}\n"
        f"⭐ Уровень: {data['level']}\n"
        f"⚔️ Класс: {data['class_name']}\n"
        f"🎧 TeamSpeak: {data['teamspeak']}\n"
        f"📱 Telegram: {data['telegram']}\n\n"
        "Всё верно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Принять", callback_data="newbie_confirm"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data="newbie_reject"),
        ]]),
        parse_mode="HTML",
    )
    storage.save_newbie_message_ids(
        message.chat.id, user_id, confirmation_message_id=confirmation_message.message_id
    )
    storage.add_newbie_message(message.chat.id, user_id, confirmation_message.message_id)


@dp.callback_query(F.data == "newbie_confirm")
async def newbie_confirm_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if callback.message is None:
        await callback.answer("Не удалось найти анкету.", show_alert=True)
        return
    chat_id = callback.message.chat.id
    session = _newbie_sessions.get(user_id)
    data = session["data"] if session and session["chat_id"] == chat_id else storage.get_newbie_draft(chat_id, user_id)
    if not data or not data.get("game_nickname"):
        await callback.answer("Анкета устарела. Запусти /newbie ещё раз.", show_alert=True)
        return
    await callback.answer("Сохраняю…")

    added_by_username = _normalize_username(callback.from_user.username)
    added_by_display_name = callback.from_user.full_name or callback.from_user.first_name or ""
    try:
        ok = storage.add_recruit(
            chat_id,
            data["game_nickname"],
            data["level"],
            data["class_name"],
            data["teamspeak"],
            data["telegram"],
            user_id,
            added_by_username or None,
            added_by_display_name,
        )
        if not ok:
            await callback.answer("Такой игрок уже есть", show_alert=True)
            await _close_newbie_session(callback, None)
            return

        # Сразу закрываем сессию в памяти и удаляем черновик.
        # После этого обычные сообщения пользователя уже не считаются частью /newbie.
        _newbie_sessions.pop(user_id, None)
        storage.delete_newbie_draft(chat_id, user_id)

        # Отправляем принятого новичка в Google Таблицу.
        # Ошибка синхронизации не отменяет принятие в самой Алине.
        await _send_recruit_to_google_sheets(
            data,
            added_by_username,
            added_by_display_name,
        )

        # Убираем все сообщения текущей анкеты и все напоминания.
        await _close_newbie_session(callback, None)
    except Exception:
        logging.exception("Failed to finalize newbie acceptance")
        # Даже если Telegram не дал удалить сообщение, анкета не должна оставаться активной.
        _newbie_sessions.pop(user_id, None)
        storage.delete_newbie_draft(chat_id, user_id)
        storage.delete_newbie_message_ids(chat_id, user_id)
        storage.delete_newbie_messages(chat_id, user_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        raise


def _parse_analytics_command(text: str):
    match = re.match(r"^/analytics(?:@\\w+)?(?:\\s+(.+))?\\s*$", text or "", re.I)
    if not match:
        return None
    target = (match.group(1) or "all").strip()
    return target or "all"


@dp.message(
    F.text,
    lambda message: _parse_analytics_command((message.text or "").strip()) is not None,
)
async def command_analytics(message: Message):
    if not _is_allowed_chat(message):
        return
    target = _parse_analytics_command(message.text or "")
    if target is None:
        return

    if target.lower() in {"all", "все", "всё"}:
        total, by_adder = storage.recruit_analytics_all(message.chat.id)
        if not total:
            await message.answer("📊 Аналитика набора пока пустая.")
            return

        lines = [
            "📊 <b>Аналитика набора</b>",
            "",
            f"👥 Всего принято: <b>{total}</b>",
            "",
            "👤 <b>По игрокам, которые принимали:</b>",
        ]
        for username, display_name, count in by_adder:
            who = f"@{username}" if username else (display_name or "неизвестно")
            lines.append(f"• {who} — <b>{count}</b>")

        await message.answer("\\n".join(lines), parse_mode="HTML")
        return

    target = target.lstrip("@").strip()
    rows = storage.recruit_analytics_user(message.chat.id, target)
    if not rows:
        await message.answer(f"📊 У @{target} пока нет принятых через /newbie игроков.")
        return

    lines = [
        "📊 <b>Аналитика набора</b>",
        "",
        f"👤 Участник: <b>@{target}</b>",
        f"👥 Принято: <b>{len(rows)}</b>",
        "",
        "📋 <b>Список:</b>",
    ]
    for index, (nickname, level, class_name, teamspeak, telegram, created_at) in enumerate(rows, 1):
        lines.append(
            f"{index}. {nickname} — {level or '—'}, {class_name or '—'} "
            f"({created_at[:10]})"
        )

    await message.answer("\\n".join(lines), parse_mode="HTML")


@dp.message(
    F.text,
    lambda message: _is_allowed_chat(message)
    and _addressed_to_alina((message.text or "").strip())
    and _parse_recruiter_query((message.text or "").strip()) is not None,
)
async def command_recruiter_list(message: Message):
    recruiter = _parse_recruiter_query(message.text or "")
    if not recruiter:
        return

    if recruiter == "__SELF__":
        username = _normalize_username(message.from_user.username if message.from_user else None)
        user_id = message.from_user.id if message.from_user else None
        rows = storage.recruits_by_adder_user_id(message.chat.id, user_id) if user_id else []
        display = f"@{username}" if username else (message.from_user.full_name if message.from_user else "ты")
    else:
        rows = storage.recruits_by_adder(message.chat.id, recruiter)
        display = f"@{recruiter}"

    if not rows:
        await message.answer(f"📋 У {display} пока нет записанных через /newbie игроков.")
        return

    header = f"📋 Игроки, которых принял {display}:\n\n"
    blocks = []
    for index, (nickname, level, class_name, teamspeak, telegram, created_at) in enumerate(rows, 1):
        date_text = created_at[:10]
        blocks.append(
            f"{index}. 🎮 {nickname}\n"
            f"   ⭐ {level or '—'} | ⚔️ {class_name or '—'}\n"
            f"   🎧 TS: {teamspeak or '—'} | 📱 TG: {telegram or '—'}\n"
            f"   📅 {date_text}"
        )

    chunks = []
    current = header
    for block in blocks:
        candidate = current + block + "\n\n"
        if len(candidate) > 3800 and current != header:
            chunks.append(current.rstrip())
            current = block + "\n\n"
        else:
            current = candidate
    if current.strip():
        chunks.append(current.rstrip())

    for chunk in chunks:
        await message.answer(chunk)


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


@dp.message(Command('start'))
async def command_start(message: Message):
    if not _is_allowed_chat(message): return
    storage.set_chat_enabled(message.chat.id, True)
    await message.answer('🟢 Бот запущен. Теперь отвечаю на сообщения.')


@dp.message(Command('stop'))
async def command_stop(message: Message):
    if not _is_allowed_chat(message): return
    storage.set_chat_enabled(message.chat.id, False)
    await message.answer('🔴 Бот остановлен. Команду /start можно использовать для запуска.')


@dp.message(Command('status'))
async def command_status(message: Message):
    if not _is_allowed_chat(message): return
    await message.answer(f"Статус бота: {'🟢 запущен' if storage.is_chat_enabled(message.chat.id) else '🔴 остановлен'}.")


@dp.callback_query(F.data == "yt_test_like")
async def callback_yt_test_like(callback: CallbackQuery):
    if callback.message is None or not _is_allowed_chat(callback.message):
        await callback.answer()
        return

    username = callback.from_user.username if callback.from_user else None
    if not is_authorized(username):
        await callback.answer("Эта кнопка доступна только авторизованным пользователям.", show_alert=True)
        return

    await callback.answer("Запускаю проверку YouTube…")

    try:
        latest = await asyncio.to_thread(_latest_video)
        if not latest:
            await callback.message.answer("Не смогла найти последнее видео @k4mui_play.")
            return

        video_id, title, _url, _published = latest
        ok = await asyncio.to_thread(like_video, video_id)

        if ok:
            text = (
                f"🧪 Тест завершён.\n\n"
                f"Видео: «{title}»\n"
                f"👍 Лайк поставлен или уже был установлен ранее.\n"
                f"Аккаунт: linaabildina@gmail.com"
            )
        else:
            text = (
                f"🧪 Тест не пройден.\n\n"
                f"Видео: «{title}»\n"
                f"👍 Лайк не поставлен.\n"
                f"Проверь открывшийся Chromium: активным должен быть аккаунт linaabildina@gmail.com."
            )

        await callback.message.answer(text)
    except Exception:
        logging.exception("YouTube like test failed")
        await callback.message.answer(
            "🧪 Тест не пройден. Не удалось выполнить действие в YouTube. "
            "Проверь Playwright/Chromium и авторизацию аккаунта linaabildina@gmail.com."
        )


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


@dp.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    """Автоматически приветствует новых участников группы."""
    if not _is_allowed_chat(message):
        return

    new_members = [member for member in (message.new_chat_members or []) if not (_bot_id and member.id == _bot_id)]
    if not new_members:
        return

    greetings = [
        "Добро пожаловать, {name}! 👋 Осваивайся, у нас тут весело 😏",
        "О, новенький! {name}, добро пожаловать в клан 👀",
        "Встречаем {name}! 👋 Заходи, располагайся.",
        "{name}, добро пожаловать! 😌 Теперь ты официально с нами.",
        "Так-так, к нам прибыло подкрепление — {name}! 🔥 Добро пожаловать!",
    ]

    names = [member.full_name or member.first_name or "новенький" for member in new_members]
    if len(names) == 1:
        text = random.choice(greetings).format(name=names[0])
    else:
        text = "Добро пожаловать в клан! 👋\\n\\n" + "\\n".join(f"• {name}" for name in names)
        text += "\\n\\nОсваивайтесь, теперь вы с нами 😏"

    await message.bot.send_message(
        settings.group_chat_id,
        text,
        message_thread_id=2,
    )


@dp.message(F.text)
async def on_message(message: Message):
    global _bot_id
    if not _is_allowed_chat(message): return
    original_text = (message.text or '').strip()
    if not original_text: return
    if _bot_id is not None and message.from_user and message.from_user.id == _bot_id: return
    if original_text.split()[0].split('@')[0].lower() in {'/start','/stop','/status','/consultant','/watch','/watches','/unwatch','/history','/market','/reminders','/cancel','/newbie'}: return
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

    recruiter = _parse_recruiter_query(original_text)
    if recruiter and _is_allowed_chat(message) and _addressed_to_alina(original_text):
        await command_recruiter_list(message)
        return

    if not _addressed_to_alina(original_text) and not is_reply_to_alina: return

    text = original_text

    # Вопросы о YouTube-канале обрабатываем отдельно: Алина может
    # проверить реальный статус лайка авторизованного аккаунта.
    if _is_youtube_question(text):
        try:
            answer = await _youtube_status_answer()
        except Exception:
            logging.exception("YouTube status check failed")
            answer = "Не смогла проверить статус лайка на YouTube. Авторизация аккаунта ещё не подключена или доступ временно недоступен."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🧪 Тест: поставить лайк", callback_data="yt_test_like")
        ]])
        await message.answer(answer, reply_to_message_id=message.message_id, reply_markup=keyboard)
        storage.add(message.chat.id, None, None, 'assistant', answer)
        return

    # Если участник явно исправляет Алину, сохраняем это как приоритетную
    # корректировку знаний. Специальная команда не нужна.
    if _is_knowledge_correction(text):
        storage.add_knowledge_correction(message.chat.id, text)
        logging.info("[KNOWLEDGE] Saved user correction: %s", text[:300])

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

    await asyncio.to_thread(monitor_forever, settings.db_path, send_message, like_video)


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