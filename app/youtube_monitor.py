import logging
import random
import re
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


CHANNEL_URL = "https://www.youtube.com/@k4mui_play"
POLL_SECONDS = 300


def _fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", "ignore")


def _channel_id() -> str:
    html = _fetch(CHANNEL_URL)
    patterns = [
        r'"channelId":"(UC[0-9A-Za-z_-]+)"',
        r'"externalId":"(UC[0-9A-Za-z_-]+)"',
        r'<meta itemprop="channelId" content="(UC[0-9A-Za-z_-]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    raise RuntimeError("Не удалось определить channel_id YouTube")


def _latest_video():
    channel_id = _channel_id()
    xml = _fetch(
        "https://www.youtube.com/feeds/videos.xml?"
        + urllib.parse.urlencode({"channel_id": channel_id})
    )
    root = ET.fromstring(xml)
    ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if not entries:
        return None
    entry = entries[0]
    video_id = entry.findtext("yt:videoId", namespaces=ns)
    title = entry.findtext("atom:title", namespaces=ns)
    published = entry.findtext("atom:published", namespaces=ns)
    link = entry.find("atom:link", ns)
    href = link.attrib.get("href") if link is not None else ""
    if not video_id:
        return None
    return video_id, (title or "Новое видео").strip(), href or f"https://www.youtube.com/watch?v={video_id}", published or ""


def _get_last(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS youtube_monitor_state "
            "(channel TEXT PRIMARY KEY, last_video_id TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT last_video_id FROM youtube_monitor_state WHERE channel = ?",
            (CHANNEL_URL,),
        ).fetchone()
        return row[0] if row else None


def _set_last(db_path: str, video_id: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO youtube_monitor_state(channel, last_video_id) VALUES (?, ?) "
            "ON CONFLICT(channel) DO UPDATE SET last_video_id=excluded.last_video_id",
            (CHANNEL_URL, video_id),
        )
        conn.commit()


def check_new_video(db_path: str):
    latest = _latest_video()
    if not latest:
        return None

    video_id, title, url, published = latest
    last_id = _get_last(db_path)

    if last_id is None:
        _set_last(db_path, video_id)
        logging.info("YouTube monitor initialized with video %s", video_id)
        return None

    if video_id == last_id:
        return None

    _set_last(db_path, video_id)
    return title, url, published


def monitor_forever(db_path: str, send_message):
    logging.info("YouTube monitor started: %s", CHANNEL_URL)
    while True:
        try:
            new_video = check_new_video(db_path)
            if new_video:
                title, url, published = new_video
                messages = [
                    f"😌 Я уже посмотрела и лайкнула новый ролик @k4mui_play.\n\n🎬 {title}\n\nЕсли ещё не смотрели — вот он 👇\n{url}",
                    f"👀 Так-так... новый ролик у @k4mui_play уже вышел.\n\nЯ, конечно, уже посмотрела и лайкнула 😌\n\n🎬 {title}\n🔗 {url}",
                    f"💅 Не ждала вас — я уже сходила, посмотрела и поставила лайк.\n\n🎬 Новый ролик @k4mui_play:\n{title}\n\n👇 Ловите ссылку:\n{url}",
                    f"🥰 Новый ролик вышел! Я уже всё посмотрела и лайкнула, можете не переживать.\n\n🎬 {title}\n\n🔗 {url}",
                    f"📢 Докладываю: @k4mui_play снова выпустил ролик.\n\nА я уже посмотрела и лайкнула 😎\n\n🎬 {title}\n🔗 {url}",
                ]
                send_message(random.choice(messages))
        except Exception:
            logging.exception("YouTube monitor check failed")
        import time
        time.sleep(POLL_SECONDS)
