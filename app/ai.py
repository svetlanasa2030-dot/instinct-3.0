import asyncio
from openai import AsyncOpenAI

from .knowledge import search_knowledge
from .storage import Storage


class AIEngine:
    def __init__(
        self,
        openai_key: str,
        openai_model: str,
        system_prompt: str,
        storage: Storage,
        provider: str = "openai",
        gemini_key: str = "",
        gemini_model: str = "gemini-2.5-flash",
    ):
        self.openai = AsyncOpenAI(api_key=openai_key)
        self.openai_model = openai_model
        self.system_prompt = system_prompt
        self.storage = storage
        self.provider = (provider or "openai").strip().lower()
        self.gemini_key = gemini_key
        self.gemini_model = gemini_model

    async def _generate(self, messages: list[dict], temperature: float = 0.8) -> str:
        if self.provider == "gemini":
            if not self.gemini_key:
                raise RuntimeError("Выбран Gemini, но GEMINI_API_KEY не указан")

            from google import genai

            prompt = "\n\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in messages
            )

            def call_gemini():
                client = genai.Client(api_key=self.gemini_key)
                response = client.models.generate_content(
                    model=self.gemini_model,
                    contents=prompt,
                )
                return (response.text or "").strip()

            answer = await asyncio.to_thread(call_gemini)
            if not answer:
                raise RuntimeError("Gemini не вернул текстовый ответ")
            return answer

        response = await self.openai.responses.create(
            model=self.openai_model,
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
                "Не отвечай только на бессмысленные сообщения или спам. "
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
        return await self._generate(messages, temperature=0.9)
