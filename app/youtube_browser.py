import logging
import os
import re
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


CHANNEL_URL = "https://www.youtube.com/@k4mui_play"
DEFAULT_PROFILE_DIR = "youtube_profile"
_browser_lock = threading.Lock()


def _profile_dir() -> Path:
    configured = os.getenv("YOUTUBE_BROWSER_PROFILE", "").strip()
    if configured:
        path = Path(configured).expanduser()
    else:
        appdata = os.getenv("APPDATA")
        base = Path(appdata) / "InstinctBot" if appdata else Path.home() / ".instinct_bot"
        path = base / DEFAULT_PROFILE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _like_button(page):
    selectors = [
        'button[aria-label*="like this video" i]',
        'button[aria-label*="нравится" i]',
        'button[title*="like this video" i]',
        'button[title*="нравится" i]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=2500):
                return locator
        except Exception:
            continue
    return None


def _already_liked(button) -> bool:
    try:
        aria = (button.get_attribute("aria-label") or "").lower()
        title = (button.get_attribute("title") or "").lower()
        text = f"{aria} {title}"
        return any(x in text for x in ("unlike", "не нравится", "убрать отметку", "remove like"))
    except Exception:
        return False


def _open_context(playwright):
    return playwright.chromium.launch_persistent_context(
        str(_profile_dir()),
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def _wait_for_login_or_video(page, video_url: str):
    page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    button = _like_button(page)
    if button:
        return button

    logging.warning(
        "YouTube Like button is unavailable. If Google login is required, "
        "complete login in the opened browser window and keep it open."
    )

    try:
        page.wait_for_function(
            """() => {
                const text = document.body?.innerText || '';
                return !/sign in|войти|войдите|вход/i.test(text);
            }""",
            timeout=120000,
        )
    except PlaywrightTimeoutError:
        pass

    for _ in range(30):
        button = _like_button(page)
        if button:
            return button
        page.wait_for_timeout(2000)

    return None


def like_video(video_id: str) -> bool:
    """Put a real YouTube Like using a persistent browser session.

    On first use, a visible Chromium window opens so the account owner can
    sign in to YouTube manually. Passwords are never stored by this code.
    """
    if not video_id:
        return False

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    with _browser_lock:
        with sync_playwright() as playwright:
            context = _open_context(playwright)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                button = _wait_for_login_or_video(page, video_url)
                if button is None:
                    logging.error("Could not find YouTube Like button for %s", video_id)
                    return False

                if _already_liked(button):
                    logging.info("YouTube video %s is already liked", video_id)
                    return True

                button.click(timeout=10000)
                page.wait_for_timeout(1500)

                updated = _like_button(page)
                if updated and _already_liked(updated):
                    logging.info("YouTube video %s liked successfully", video_id)
                    return True

                logging.warning("YouTube Like click was not confirmed for %s", video_id)
                return False
            except Exception:
                logging.exception("Browser YouTube Like failed for %s", video_id)
                return False
            finally:
                context.close()


def get_video_rating(video_id: str) -> str:
    """Check whether the persistent YouTube session has liked the video."""
    if not video_id:
        return "unspecified"

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    with _browser_lock:
        with sync_playwright() as playwright:
            context = _open_context(playwright)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                button = _wait_for_login_or_video(page, video_url)
                if button is None:
                    return "unspecified"
                return "like" if _already_liked(button) else "none"
            except Exception:
                logging.exception("Browser YouTube rating check failed for %s", video_id)
                return "unspecified"
            finally:
                context.close()
