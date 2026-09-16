import re

from openai import AsyncOpenAI

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

    async def _generate(self, messages: list[dict]) -> str:
        response = await self.client.responses.create(model=self.model, input=messages)
        answer = (response.output_text or "").strip()
        if not answer:
            raise RuntimeError("OpenAI не вернул текстовый ответ")
        return answer

    async def decide_and_answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)

        # Для вопросов по Perfect World дополнительно ищем актуальную
        # информацию в открытом интернете и передаём содержимое страниц модели.
        web_context = ""
        comeback_context = ""
        try:
            comeback_context = search_comeback_cats(user_text)
        except Exception:
            pass

        try:
            web_context = search_web("Perfect World " + user_text, limit=5)
        except Exception:
            pass

        if comeback_context:
            knowledge += "\n\nОсновной источник ComebackPW:\n" + comeback_context
        if web_context:
            knowledge += "\n\nДополнительная информация из интернета:\n" + web_context

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
                "сверяй факты по найденным источникам, не выдумывай отсутствующие данные."
            )},
            {"role": "system", "content": f"База знаний и веб-источники:\n{knowledge}"},
        ]
        for role, content in context[-20:]:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        answer = await self._generate(messages)

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
