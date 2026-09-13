from openai import AsyncOpenAI
from google import genai
import asyncio

from .knowledge import search_knowledge
from .storage import Storage

class AIEngine:
    def __init__(self, provider: str, openai_key: str, openai_model: str, gemini_key: str, gemini_model: str, system_prompt: str, storage: Storage):
        self.provider = (provider or "openai").strip().lower()
        self.openai_model = openai_model
        self.gemini_model = gemini_model
        self.system_prompt = system_prompt
        self.storage = storage
        self.openai = AsyncOpenAI(api_key=openai_key) if openai_key else None
        self.gemini = genai.Client(api_key=gemini_key) if gemini_key else None

    async def _generate(self, messages, temperature=0.8) -> str:
        if self.provider == "gemini":
            if self.gemini is None:
                raise RuntimeError("Gemini API Key не указан.")
            prompt = "\n\n".join(
                f"{m['role']}: {m['content']}" for m in messages
            )
            response = await asyncio.to_thread(
                self.gemini.models.generate_content,
                model=self.gemini_model,
                contents=prompt,
            )
            return (response.text or "").strip()
        if self.openai is None:
            raise RuntimeError("OpenAI API Key не указан.")
        response = await self.openai.chat.completions.create(
            model=self.openai_model,
            messages=messages,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    async def decide_and_answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": (
                "Ты участвуешь в групповом Telegram-чате. Ты видишь каждое новое сообщение. "
                "Сам реши, нужно ли сейчас отвечать. Не отвечай на каждую реплику и не спамь. "
                "Отвечай только если это уместно по основному промту, сообщение обращено к тебе "
                "или твой ответ действительно полезен для разговора. Если отвечать не нужно, "
                "верни ровно NO_REPLY без дополнительных слов. Если отвечать нужно, верни только "
                "готовый текст сообщения без префиксов и пояснений."
            )},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
        ]
        for role, content in context[-20:]:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        answer = await self._generate(messages, temperature=0.8)
        return "" if answer.upper() == "NO_REPLY" else answer

    async def answer(self, chat_id: int, user_text: str) -> str:
        context = self.storage.recent(chat_id)
        knowledge = search_knowledge(user_text)
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "system", "content": f"База знаний:\n{knowledge}"}]
        for role, content in context:
            if role in {"user", "assistant"}:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return await self._generate(messages, temperature=0.8)

    async def initiative(self, chat_id: int, initiative_prompt: str) -> str:
        history = self.storage.recent(chat_id)
        recent_text = "\n".join(f"{role}: {content}" for role, content in history[-15:])
        knowledge = search_knowledge(recent_text or "общение в группе")
        messages = [
            {"role": "system", "content": initiative_prompt},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
            {"role": "user", "content": f"Недавняя переписка:\n{recent_text}\n\nСгенерируй одну уместную реплику."},
        ]
        return await self._generate(messages, temperature=0.9)
