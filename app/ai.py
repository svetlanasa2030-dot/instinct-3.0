from openai import AsyncOpenAI

from .knowledge import search_knowledge
from .storage import Storage

class AIEngine:
    def __init__(self, api_key: str, model: str, system_prompt: str, storage: Storage):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.storage = storage

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

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
        )
        answer = (response.choices[0].message.content or "").strip()
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
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.8,
        )
        return (response.choices[0].message.content or "").strip()

    async def initiative(self, chat_id: int, initiative_prompt: str) -> str:
        history = self.storage.recent(chat_id)
        recent_text = "\n".join(f"{role}: {content}" for role, content in history[-15:])
        knowledge = search_knowledge(recent_text or "общение в группе")
        messages = [
            {"role": "system", "content": initiative_prompt},
            {"role": "system", "content": f"База знаний:\n{knowledge}"},
            {"role": "user", "content": f"Недавняя переписка:\n{recent_text}\n\nСгенерируй одну уместную реплику."},
        ]
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.9,
        )
        return (response.choices[0].message.content or "").strip()
