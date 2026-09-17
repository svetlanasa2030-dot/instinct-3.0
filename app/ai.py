import logging
import re

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_IDENTITY_QUESTION = re.compile(
    r"(?i)(кто тебя создал|кто тебя разработал|на какой модели|какая у тебя модель|"
    r"ты\s+(chatgpt|gpt|openai)|это\s+openai|какая у тебя нейросеть|"
    r"ты искусственный интеллект|ты ии|кто ты такой)"
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
            kwargs["tools"] = [{
                "type": "web_search",
                "search_context_size": "high",
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
            comeback_context = search_comeback_cats(user_text)
            if comeback_context:
                logger.info("[SEARCH] База котов: получено %s chars", len(comeback_context))
        except Exception as exc:
            logger.exception("[SEARCH] База котов ERROR: %s", exc)

        try:
            web_query = "site:comeback.pw/cats/146/ Perfect World ComebackPW 1.4.6 " + user_text
            web_context = search_web(web_query, limit=5)
        except Exception as exc:
            logger.exception("[SEARCH] Bing ERROR: %s", exc)

        if comeback_context:
            knowledge += "\n\nИсточник №1 — База котов ComebackPW 1.4.6:\n" + comeback_context
        if web_context:
            knowledge += "\n\nДополнительные источники:\n" + web_context

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": (
                "Отвечай сразу по существу. Если вопрос относится к Perfect World/ComebackPW, дай ответ. "
                "Не используй технические отговорки и не упоминай внутреннюю работу поиска.\n\n"
                "ПРАВИЛО БАЗЫ КОТОВ — СКУПКА И ПРОДАЖА ЭТО РАЗНЫЕ ВЕЩИ. "
                "В базе котов у объявления могут быть одновременно цена ПРОДАЖИ и цена СКУПКИ. "
                "Никогда не путай их и не выдавай цену скупки за цену продажи или наоборот.\n\n"
                "Если пользователь спрашивает «где купить», «у кого купить», «кто продаёт», "
                "«где продают» или хочет купить предмет — показывай только объявления ПРОДАЖИ: "
                "игрок, цена продажи и координаты. Цену СКУПКИ в таком ответе не показывай.\n\n"
                "Если пользователь спрашивает «кто скупает», «где скупают», «у кого продать», "
                "«кому продать», «кто покупает у игроков» или хочет продать предмет — показывай только "
                "объявления СКУПКИ: игрок, цена скупки и координаты. Цену ПРОДАЖИ в таком ответе не показывай.\n\n"
                "Если пользователь явно спрашивает и про продажу, и про скупку — разделяй ответ на два блока: "
                "«Продажа» и «Скупка». Не смешивай цены.\n\n"
                "Источник «База котов ComebackPW 1.4.6» имеет абсолютный приоритет для вопросов о котах. "
                "Если там есть объявления, используй именно их. Не заменяй продавцов NPC, крафтом, дропом или рецептом. "
                "Не выдумывай ник, цену или координаты.\n\n"
                "ВАЖНО: встроенный OpenAI Web Search используй как настоящий веб-поиск, аналогичный поиску ChatGPT. "
                "Для базы котов проверяй прямые страницы вида https://comeback.pw/cats/146/?item_id=ID, если известен ID. "
                "Если в источнике есть URL базы котов с item_id, открой именно эту страницу и используй её данные.\n\n"
                "Если источник базы содержит объявления нужного типа, не говори, что их нет. "
                "Если нужных объявлений действительно нет, только тогда сообщи об этом.\n\n"
                "Для покупки ответ должен быть коротким: «Нашла: • Игрок — цена продажи — координаты». "
                "Для скупки: «Нашла: • Игрок — цена скупки — координаты»."
            )},
            {"role": "system", "content": f"Предварительные источники:\n{knowledge}"},
        ]
        for role, content in context[-20:]:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        answer = await self._generate(messages, web_search=True)

        if _IDENTITY_QUESTION.search(user_text):
            return "я Алина 🙂"

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
