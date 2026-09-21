import asyncio
import random
from datetime import datetime, timedelta


EVENTS = [
    "В чате подозрительно тихо. Брось короткую дерзкую провокацию про Perfect World и предложи людям оживиться.",
    "Придумай короткий игровой вопрос для клана: кто сегодня самый опасный игрок и почему. Сделай это с юмором.",
    "Устрой маленькую случайную угадайку по Perfect World ComebackPW v146 на одно сообщение.",
    "Подкинь в чат короткий абсурдный игровой вопрос, чтобы люди начали спорить или шутить.",
    "Придумай короткий вызов клану на сегодня, связанный с Perfect World, без сложных правил.",
]


async def run_random_events(bot, ai, storage, chat_id: int):
    while True:
        now = datetime.now().astimezone()
        count = random.choice((2, 3))
        start = now.replace(hour=10, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if now >= end:
            start = start + timedelta(days=1)
            end = end + timedelta(days=1)
        elif now < start:
            pass
        else:
            start = now + timedelta(minutes=30)
        total_minutes = max(60, int((end - start).total_seconds() // 60))
        points = sorted(random.sample(range(total_minutes), min(count, max(1, total_minutes))))
        for offset in points:
            target = start + timedelta(minutes=offset)
            delay = max(5, (target - datetime.now().astimezone()).total_seconds())
            await asyncio.sleep(delay)
            try:
                history = storage.recent(chat_id, 12)
                recent = "\n".join(f"{r}: {c}" for r, c in history)
                prompt = (
                    "Ты Алина в клановом чате. Сгенерируй одну короткую живую реплику-событие. "
                    "Не объясняй, что это автоматическое событие. Не упоминай таймеры, расписание, бота или внутренние механизмы. "
                    "Учитывай недавнюю переписку и не повторяй недавнюю тему. Можно немного дерзости и мата, если уместно.\n"
                    f"Идея события: {random.choice(EVENTS)}\nНедавняя переписка:\n{recent}"
                )
                answer = await ai._generate([
                    {"role": "system", "content": ai.system_prompt},
                    {"role": "user", "content": prompt},
                ])
                answer = answer.strip()
                if answer and answer.upper() != "NO_REPLY":
                    await bot.send_message(chat_id, answer)
                    storage.add(chat_id, None, None, "assistant", answer)
            except Exception:
                continue
        await asyncio.sleep(60)
