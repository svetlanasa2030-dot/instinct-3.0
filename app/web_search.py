import concurrent.futures
import logging
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_h2 = False
        self._href = None
        self._title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h2":
            self._in_h2 = True
            self._href = None
            self._title = []
        elif tag == "a" and self._in_h2 and attrs.get("href"):
            self._href = attrs["href"]

    def handle_endtag(self, tag):
        if tag == "h2" and self._in_h2:
            title = re.sub(r"\s+", " ", "".join(self._title)).strip()
            if title and self._href:
                self.results.append((title, self._href))
            self._in_h2 = False

    def handle_data(self, data):
        if self._in_h2:
            self._title.append(data)


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.parts.append(text)


def _fetch_page(url: str, max_chars: int = 12000) -> str:
    try:
        logger.debug("[CATS] HTTP GET %s", url)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
                "Accept-Language": "ru,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            status = getattr(response, "status", 200)
            logger.debug("[CATS] HTTP %s %s Content-Type=%s", status, url, content_type)
            if "text/html" not in content_type.lower():
                logger.warning("[CATS] Non-HTML response: %s", content_type)
                return ""
            data = response.read(2_000_000).decode("utf-8", "ignore")
        parser = _TextParser()
        parser.feed(data)
        text = " ".join(parser.parts)
        logger.debug("[CATS] Parsed %s chars from %s", len(text), url)
        return text[:max_chars]
    except Exception as exc:
        logger.warning("[CATS] HTTP ERROR %s: %s", url, exc)
        return ""


COMEBACK_CATS_BASE = "https://comeback.pw/cats/146/"
COMEBACK_CATS_PAGES = 410


def _query_words(query: str) -> list[str]:
    words = re.findall(r"[\wа-яА-ЯёЁ-]{2,}", query.lower())
    stop_words = {
        "где", "найти", "найди", "есть", "мне", "нужен", "нужна", "нужно",
        "можно", "как", "какой", "какая", "какие", "покажи", "покажите",
        "координаты", "координата", "кот", "кота", "коте", "котом", "локация",
        "место", "месте", "цена", "стоимость", "продажа", "покупка", "купить",
        "продать", "продается", "продаётся", "продают", "продается",
    }
    return [w for w in words if w not in stop_words]


def _normalize_item_query(query: str) -> str:
    words = _query_words(query)
    return " ".join(words).strip()


def _extract_item_urls(html: str) -> list[str]:
    """Extract item URLs even when Bing changes its result markup."""
    urls = re.findall(r"https?://(?:www\.)?comeback\.pw/db/146/item/\d+", html, flags=re.I)
    result = []
    seen = set()
    for url in urls:
        clean = url.rstrip("/&?.,\")'\\")
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _find_item_id(query: str) -> tuple[int | None, str]:
    item_query = _normalize_item_query(query)
    logger.info("[CATS] Запрос: %s", query)
    logger.info("[CATS] Нормализовано: %s", item_query)
    if not item_query:
        logger.warning("[CATS] Не удалось выделить название предмета")
        return None, ""

    # Bing markup changes from time to time. Run several equivalent searches
    # and parse both structured h2 results and raw /db/146/item/<id> URLs.
    variants = [
        f'site:comeback.pw/db/146/item/ "{item_query}"',
        f'site:comeback.pw/db/146/item/ "★{item_query}"',
        f'site:comeback.pw/db/146/item/ {item_query}',
    ]
    candidates: list[str] = []
    seen = set()

    for search_query in variants:
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({
            "q": search_query,
            "count": 10,
            "setlang": "ru",
        })
        logger.info("[CATS] Поиск ID предмета: %s", search_url)
        try:
            request = urllib.request.Request(
                search_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "ru,en;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                data = response.read().decode("utf-8", "ignore")
        except Exception as exc:
            logger.warning("[CATS] Ошибка Bing: %s", exc)
            continue

        parser = _BingParser()
        parser.feed(data)
        raw_urls = _extract_item_urls(data)
        structured_urls = [url for _, url in parser.results]
        for url in structured_urls + raw_urls:
            match = re.search(r"/db/146/item/(\d+)", url)
            if not match:
                continue
            normalized_url = f"https://comeback.pw/db/146/item/{match.group(1)}"
            if normalized_url not in seen:
                seen.add(normalized_url)
                candidates.append(normalized_url)
        logger.info("[CATS] Bing результатов=%s, кандидатов URL=%s", len(parser.results), len(candidates))

        if candidates:
            # One successful search is normally enough; keep the variants only
            # when the first one returned no indexed item URLs.
            break

    wanted = [w for w in re.findall(r"[\wа-яА-ЯёЁ-]{2,}", item_query.lower()) if len(w) >= 3]
    wanted_norm = " ".join(wanted)

    scored = []
    for url in candidates:
        item_id = int(re.search(r"/item/(\d+)", url).group(1))
        page_text = _fetch_page(url, max_chars=5000)
        normalized = page_text.lower()
        if not wanted or not all(word in normalized for word in wanted):
            continue
        # Prefer pages where the item name occurs close to the beginning.
        position = normalized.find(wanted[0]) if wanted else 999999
        score = sum(word in normalized[:1800] for word in wanted) * 100 - max(position, 0)
        scored.append((score, item_id, url, page_text[:500]))

    if scored:
        scored.sort(reverse=True)
        _, item_id, url, preview = scored[0]
        logger.info("[CATS] ID предмета подтвержден: %s | %s", item_id, preview[:180])
        return item_id, url

    logger.warning("[CATS] ID предмета не найден: %s", wanted_norm)
    return None, ""


def _find_matches(page: int, query_words: list[str]) -> str:
    url = COMEBACK_CATS_BASE + "?page=" + str(page)
    text = _fetch_page(url)
    if not text:
        return ""
    normalized = text.lower()
    if not query_words or not all(word in normalized for word in query_words):
        return ""
    fragments = []
    used_ranges = []
    for word in query_words:
        start = 0
        while True:
            pos = normalized.find(word, start)
            if pos < 0:
                break
            left = max(0, pos - 700)
            right = min(len(text), pos + 1500)
            if not any(left < old_right and right > old_left for old_left, old_right in used_ranges):
                fragments.append(text[left:right].strip())
                used_ranges.append((left, right))
            start = pos + len(word)
            if len(fragments) >= 5:
                break
        if len(fragments) >= 5:
            break
    if not fragments:
        return ""
    return (
        f"Источник: ComebackPW — категория 146, страница {page}\n"
        f"URL: {url}\n"
        f"Совпадения: {', '.join(sorted(set(query_words)))}\n"
        f"Фрагменты:\n" + "\n---\n".join(fragments)
    )


def _search_cat_by_item_id(item_id: int, item_url: str = "") -> str:
    url = COMEBACK_CATS_BASE + "?item_id=" + str(item_id)
    logger.info("[CATS] Запрос базы котов: %s", url)
    text = _fetch_page(url, max_chars=16000)
    if not text:
        logger.warning("[CATS] База котов вернула пустой результат для ID=%s", item_id)
        return ""

    no_listings = "ничего не найдено" in text.lower()
    logger.info(
        "[CATS] База котов получена для ID=%s, %s chars, listings=%s",
        item_id, len(text), not no_listings,
    )
    return (
        f"Источник: ComebackPW — База котов 1.4.6\n"
        f"Статус базы: {'NO_LISTINGS' if no_listings else 'LISTINGS_FOUND'}\n"
        f"Предмет ID: {item_id}\n"
        f"URL: {url}\n"
        f"Страница предмета в DB: {item_url}\n"
        f"Результаты поиска котов:\n{text}"
    )


def search_comeback_cats(query: str, max_pages: int = COMEBACK_CATS_PAGES, max_workers: int = 12) -> str:
    query = query.strip()
    if not query:
        return ""

    logger.info("[CATS] ===== START SEARCH =====")
    item_id, item_url = _find_item_id(query)
    if item_id is not None:
        result = _search_cat_by_item_id(item_id, item_url)
        if result:
            logger.info("[CATS] ===== SUCCESS ID=%s =====", item_id)
            return result
        logger.warning("[CATS] Фильтр item_id не дал результата, запускаю fallback")

    words = _query_words(query)
    if not words:
        return ""
    logger.info("[CATS] Fallback: поиск по страницам, pages=%s workers=%s words=%s", min(max_pages, COMEBACK_CATS_PAGES), max_workers, words)
    pages = range(1, min(max_pages, COMEBACK_CATS_PAGES) + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda page: _find_matches(page, words), pages))
    matches = [result for result in results if result]
    logger.info("[CATS] Fallback найдено страниц: %s", len(matches))
    return "\n\n---\n\n".join(matches[:12])


def search_web(query: str, limit: int = 5) -> str:
    query = query.strip()
    if not query:
        return ""
    search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({
        "q": query,
        "count": min(max(limit, 1), 8),
        "setlang": "ru",
    })
    request = urllib.request.Request(
        search_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read().decode("utf-8", "ignore")
    parser = _BingParser()
    parser.feed(data)
    results = []
    seen = set()
    for title, url in parser.results:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or url in seen:
            continue
        seen.add(url)
        page_text = _fetch_page(url, max_chars=7000)
        if page_text:
            results.append(f"Источник: {title}\nURL: {url}\nСодержимое:\n{page_text}")
        else:
            results.append(f"Источник: {title}\nURL: {url}")
        if len(results) >= limit:
            break
    return "\n\n---\n\n".join(results)
