from openai import AsyncOpenAI

from .knowledge import search_knowledge
from .storage import Storage


class AIEngine:
    def __init__(self, api_key: str, model: str, system_prompt: str, storage: Storage):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.storage = storage

    async def _generate(self, messages: list[dict]) -> str:
        response = await self.client.responses.create(
            model=self.model,
            input=messages,
        )
        answer = (response.output_text or "").strip()
        if not answer:
            raise RuntimeError("OpenAI не вернул текстовый ответ")
        return answer

    async def decide_and_answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": (
                "Ты участвуешь в групповом Telegram-чате. "
                "Поддерживай естественный человеческий диалог. "
                "Если человеку можно полезно ответить — отвечай. "
                "Если отвечать действительно не нужно, верни ровно NO_REPLY. "
                "Если отвечаешь, верни только готовый текст сообщения."
            )},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
        ]
        for role, content in context[-20:]:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        answer = await self._generate(messages)
        return "" if answer.upper() == "NO_REPLY" else answer

    async def answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.append({"role": "system", "content": f"База знаний:\n{knowledge}"})
        for role, content in context:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return await self._generate(messages)

    async def initiative(self, chat_id: int, initiative_prompt: str) -> str:
        history = self.storage.recent(chat_id)
        recent_text = "\n".join(
            f"{role}: {content}" for role, content in history[-15:]
        )
        knowledge = search_knowledge(recent_text or "общение в группе")
        messages = [
            {"role": "system", "content": initiative_prompt},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
            {"role": "user", "content": (
                f"Недавняя переписка:\n{recent_text}\n\n"
                "Сгенерируй одну уместную реплику."
            )},
        ]
        return await self._generate(messages)
