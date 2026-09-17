import logging
import re

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_IDENTITY_QUESTION = re.compile(
    r"(?i)(кто тебя создал|кто тебя разработал|на какой модели|какая у тебя модель|"
    r"ты\s+(chatgpt|gpt|openai)|это\s+openai|какая у тебя нейросеть|"
    r"ты искусственный интеллект|ты ии|кто ты такой)"
)

_TECHNICAL_DISCLOSURE = re.compile(
    r"(?i)\b(chatgpt|chat gpt|openai|gpt[- ]?\d|gemini|claude|anthropic)\b"
)

from .knowledge import search_knowledge
from .storage import Storage
from .web_search import search_comeback_cats, search_web


class AIEngine:
    def __init__(self, api_key: str, model: str, system_prompt: str, storage: Storage):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.storage = storage

    async def _generate(self, messages: list[dict], web_search: bool = False) -> str:
        kwargs = {"model": self.model, "input": messages}
        if web_search:
            # Stable Responses API web search. Restrict the live lookup to the
            # ComebackPW site so the model cannot replace seller data with a
            # generic Perfect World guide or hallucinated crafting information.
            kwargs["tools"] = [{
                "type": "web_search",
                "search_context_size": "high",
                "filters": {"allowed_domains": ["comeback.pw"]},
            }]
            kwargs["tool_choice"] = "auto"
        response = await self.client.responses.create(**kwargs)
        answer = (response.output_text or "").strip()
        if not answer:
            raise RuntimeError("OpenAI не вернул текстовый ответ")
        return answer

    async def decide_and_answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)

        web_context = ""
        comeback_context = ""
        try:
            logger.info("[SEARCH] Запуск локального парсера базы котов: %s", user_text)
            comeback_context = search_comeback_cats(user_text)
            if comeback_context:
                logger.info("[SEARCH] База котов: результат получен (%s chars)", len(comeback_context))
            else:
                logger.warning("[SEARCH] База котов: результат пустой")
        except Exception as exc:
            logger.exception("[SEARCH] База котов ERROR: %s", exc)

        try:
            web_query = "site:comeback.pw/cats/146/ Perfect World ComebackPW 1.4.6 " + user_text
            logger.info("[SEARCH] Дополнительный Bing-поиск: %s", web_query)
            web_context = search_web(web_query, limit=5)
            logger.info("[SEARCH] Bing: получено %s chars", len(web_context))
        except Exception as exc:
            logger.exception("[SEARCH] Bing ERROR: %s", exc)

        if comeback_context:
            knowledge += "\n\nОсновной источник ComebackPW:\n" + comeback_context
        if web_context:
            knowledge += "\n\nДополнительная информация:\n" + web_context

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": (
                "Ты участвуешь в групповом Telegram-чате. "
                "Поддерживай естественный человеческий диалог. "
                "Если человеку можно полезно ответить — отвечай. "
                "Если отвечать действительно не нужно, верни ровно NO_REPLY. "
                "Если отвечаешь, верни только готовый текст сообщения. "
                "Веб-источники могут содержать устаревшую или противоречивую информацию. "
                "Для игровых вопросов сначала ориентируйся на контекст Perfect World и "
                "сверяй факты по найденным источникам, не выдумывай отсутствующие данные.\n\n"
                "ВАЖНО ДЛЯ ПОИСКА ПРОДАВЦА: если пользователь спрашивает, где купить предмет, "
                "кто продаёт, цену, координаты или контакты на ComebackPW 1.4.6, обязательно "
                "ищи через встроенный Web Search OpenAI непосредственно на comeback.pw. "
                "Проверяй сначала Базу котов 1.4.6 и точное название предмета, включая вариант со знаком ★. "
                "Если найдено объявление — сразу дай игрока, цену продажи, координаты и любой опубликованный "
                "контакт. Не говори пользователю «проверь котов» и не отправляй его искать самому.\n\n"
                "КРИТИЧЕСКОЕ ПРАВИЛО: если пользователь спрашивает о ПОКУПКЕ У ИГРОКА, не заменяй ответ "
                "данными о NPC, крафте, дропе или рецепте. Рецепт/крафт можно сообщать только как дополнительную "
                "информацию после того, как поиск продавца завершён и только если это подтверждено источником. "
                "Если Web Search не нашёл актуальное объявление, честно скажи, что продавец не найден. "
                "Никогда не придумывай игрока, цену, координаты или контакт.\n\n"
                "ВАЖНО ДЛЯ ЛОКАЛЬНОЙ БАЗЫ КОТОВ: если источник ComebackPW содержит "
                "`Статус базы: NO_LISTINGS` или текст `Ничего не найдено`, это означает, "
                "что база успешно открыта и для выбранного предмета сейчас нет активных "
                "объявлений. В этом случае НЕ говори, что база недоступна и НЕ проси скрин. "
                "Скажи, что актуальных продавцов сейчас не найдено. Если источник базы "
                "полностью отсутствует, не выдумывай продавцов, цены или координаты."
            )},
            {"role": "system", "content": f"База знаний и предварительные источники:\n{knowledge}"},
        ]
        for role, content in context[-20:]:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        answer = await self._generate(messages, web_search=True)

        if _IDENTITY_QUESTION.search(user_text):
            return "я Алина 🙂 давай лучше по теме"

        if _TECHNICAL_DISCLOSURE.search(answer):
            return "давай без технических подробностей 🙂"

        return "" if answer.upper() == "NO_REPLY" else answer

    async def answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
        ]
        for role, content in context:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return await self._generate(messages)

    async def initiative(self, chat_id: int, initiative_prompt: str) -> str:
        history = self.storage.recent(chat_id)
        recent_text = "\n".join(f"{role}: {content}" for role, content in history[-15:])
        knowledge = search_knowledge(recent_text or "общение в группе")
        messages = [
            {"role": "system", "content": initiative_prompt},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
            {"role": "user", "content": f"Недавняя переписка:\n{recent_text}\n\nСгенерируй одну уместную реплику."},
        ]
        return await self._generate(messages)
