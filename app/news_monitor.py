import asyncio
import logging
import os
from pathlib import Path

from telethon import TelegramClient, events
from telethon.sessions import StringSession


SOURCE = os.getenv("NEWS_SOURCE", "comebackpw").strip().lstrip("@")
TARGET_CHAT_ID = int(os.getenv("NEWS_TARGET_CHAT_ID", "0"))
TARGET_TOPIC_ID = int(os.getenv("NEWS_TARGET_TOPIC_ID", "6"))
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()
SESSION = os.getenv("TELEGRAM_SESSION", "").strip()

client = TelegramClient(
    StringSession(SESSION) if SESSION else str(Path.home() / ".instinct_news"),
    API_ID,
    API_HASH,
)


async def start_news_monitor():
    """Monitor a public Telegram source and forward new posts to one forum topic."""
    if not API_ID or not API_HASH or not TARGET_CHAT_ID:
        logging.warning(
            "News monitor disabled: set TELEGRAM_API_ID, TELEGRAM_API_HASH and NEWS_TARGET_CHAT_ID"
        )
        return

    await client.start()
    source = await client.get_entity(SOURCE)

    @client.on(events.NewMessage(chats=source))
    async def handler(event):
        try:
            message = event.message
            if not message or not message.id:
                return

            # Forward the original post into the selected topic.
            # reply_to is the topic/thread root in a forum supergroup.
            await client.send_message(
                TARGET_CHAT_ID,
                message,
                reply_to=TARGET_TOPIC_ID,
            )
            logging.info("Forwarded @%s message %s to topic %s", SOURCE, message.id, TARGET_TOPIC_ID)
        except Exception:
            logging.exception("Failed to forward news post")

    logging.info("News monitor started: @%s -> %s topic %s", SOURCE, TARGET_CHAT_ID, TARGET_TOPIC_ID)
    await client.run_until_disconnected()
