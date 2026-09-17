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


class _TableParser(HTMLParser):
    """Extract HTML table rows without losing seller/price/coords relationships."""
    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data):
        if not self._skip and self._cell is not None:
            self._cell.append(data)


class _HeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headings = []
        self._active = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "title"}:
            self._active = True
            self._parts = []

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "title"} and self._active:
            text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
            if text:
                self.headings.append(text)
            self._active = False

    def handle_data(self, data):
        if self._active:
            self._parts.append(data)


def _fetch_html(url: str) -> str:
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
            return response.read(2_000_000).decode("utf-8", "ignore")
    except Exception as exc:
        logger.warning("[CATS] HTTP ERROR %s: %s", url, exc)
        return ""


def _fetch_page(url: str, max_chars: int = 12000) -> str:
    data = _fetch_html(url)
    if not data:
        return ""
    parser = _TextParser()
    parser.feed(data)
    text = " ".join(parser.parts)
    logger.debug("[CATS] Parsed %s chars from %s", len(text), url)
    return text[:max_chars]


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
    return " ".join(_query_words(query)).strip()


def _normalize_name(value: str) -> str:
    value = value.lower().replace("★", " ")
    value = re.sub(r"[^\wа-яА-ЯёЁ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _extract_item_urls(html: str) -> list[str]:
    urls = re.findall(r"https?://(?:www\.)?comeback\.pw/db/146/item/\d+", html, flags=re.I)
    result, seen = [], set()
    for url in urls:
        clean = url.rstrip("/&?.,\\\"'")
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _find_item_id(query: str) -> tuple[int | None, str]:
    item_query = _normalize_item_query(query)
    logger.info("[CATS] Запрос: %s", query)
    logger.info("[CATS] Нормализовано: %s", item_query)
    if not item_query:
        return None, ""

    variants = [
        f'site:comeback.pw/db/146/item/ "{item_query}"',
        f'site:comeback.pw/db/146/item/ "★{item_query}"',
        f'site:comeback.pw/db/146/item/ {item_query}',
    ]
    candidates, seen = [], set()
    for search_query in variants:
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": search_query, "count": 10, "setlang": "ru"})
        try:
            request = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru,en;q=0.8"})
            with urllib.request.urlopen(request, timeout=12) as response:
                data = response.read().decode("utf-8", "ignore")
        except Exception as exc:
            logger.warning("[CATS] Ошибка Bing: %s", exc)
            continue
        parser = _BingParser()
        parser.feed(data)
        for url in [u for _, u in parser.results] + _extract_item_urls(data):
            match = re.search(r"/db/146/item/(\d+)", url)
            if not match:
                continue
            normalized_url = f"https://comeback.pw/db/146/item/{match.group(1)}"
            if normalized_url not in seen:
                seen.add(normalized_url)
                candidates.append(normalized_url)
        if candidates:
            break

    wanted = _normalize_name(item_query)
    scored = []
    for url in candidates:
        match = re.search(r"/item/(\d+)", url)
        if not match:
            continue
        item_id = int(match.group(1))
        html = _fetch_html(url)
        if not html:
            continue
        hp = _HeadingParser()
        hp.feed(html)
        headings = [_normalize_name(x) for x in hp.headings]
        exact_heading = any(h == wanted or wanted in h for h in headings)
        if not exact_heading:
            logger.debug("[CATS] Отклонен кандидат %s: название не в заголовке", item_id)
            continue
        score = max((1000 if h == wanted else 500 for h in headings), default=0)
        scored.append((score, item_id, url, headings[:3]))

    if scored:
        scored.sort(reverse=True)
        _, item_id, url, headings = scored[0]
        logger.info("[CATS] ID предмета подтвержден: %s | headings=%s", item_id, headings)
        return item_id, url
    logger.warning("[CATS] ID предмета не найден: %s", wanted)
    return None, ""


def _extract_cat_rows(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    best = []
    for table in parser.tables:
        header = " ".join(" ".join(row).lower() for row in table[:2])
        if any(x in header for x in ("игрок", "название кота", "продажа", "покупка", "координаты")):
            if len(table) > len(best):
                best = table
    return best


def _format_cat_rows(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = [x.lower() for x in rows[0]]
    aliases = {
        "player": ("игрок", "продавец"),
        "cat": ("название кота", "кот"),
        "sale": ("продажа", "цена продажи", "продаю"),
        "buy": ("покупка", "цена покупки", "куплю"),
        "coords": ("координаты", "координата"),
    }
    indexes = {}
    for key, names in aliases.items():
        for i, cell in enumerate(header):
            if any(name in cell for name in names):
                indexes[key] = i
                break

    # Some pages have an extra leading column, so use the known header order as fallback.
    if not indexes and len(rows[0]) >= 5:
        indexes = {"player": 0, "cat": 1, "sale": 2, "buy": 3, "coords": 4}

    out = []
    for row in rows[1:]:
        if not any(row):
            continue
        values = {key: row[i].strip() if i < len(row) else "" for key, i in indexes.items()}
        if not any(values.values()):
            continue
        out.append(
            "Игрок: {player} | Кот: {cat} | Продажа: {sale} | Покупка: {buy} | Координаты: {coords}".format(
                player=values.get("player", ""), cat=values.get("cat", ""),
                sale=values.get("sale", ""), buy=values.get("buy", ""),
                coords=values.get("coords", ""),
            )
        )
    return "\n".join(out)


def _search_cat_by_item_id(item_id: int, item_url: str = "") -> str:
    url = COMEBACK_CATS_BASE + "?item_id=" + str(item_id)
    logger.info("[CATS] Запрос базы котов: %s", url)
    html = _fetch_html(url)
    if not html:
        logger.warning("[CATS] База котов вернула пустой результат для ID=%s", item_id)
        return ""

    text_parser = _TextParser()
    text_parser.feed(html)
    text = " ".join(text_parser.parts)
    rows = _extract_cat_rows(html)
    structured = _format_cat_rows(rows)

    no_listings_text = any(x in text.lower() for x in ("ничего не найдено", "объявлений не найдено", "нет объявлений"))
    has_rows = bool(structured)
    no_listings = no_listings_text or not has_rows
    logger.info("[CATS] ID=%s chars=%s table_rows=%s listings=%s", item_id, len(text), len(rows), has_rows)

    if has_rows:
        listings = structured
    else:
        listings = text[:16000]

    return (
        "Источник: ComebackPW — База котов 1.4.6\n"
        f"Статус базы: {'LISTINGS_FOUND' if has_rows else 'NO_LISTINGS'}\n"
        f"Предмет ID: {item_id}\n"
        f"URL: {url}\n"
        f"Страница предмета в DB: {item_url}\n"
        "Результаты поиска котов:\n"
        f"{listings}"
    )


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
            left, right = max(0, pos - 700), min(len(text), pos + 1500)
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
    return f"Источник: ComebackPW — категория 146, страница {page}\nURL: {url}\nСовпадения: {', '.join(sorted(set(query_words)))}\nФрагменты:\n" + "\n---\n".join(fragments)


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
    logger.info("[CATS] Fallback: pages=%s workers=%s words=%s", min(max_pages, COMEBACK_CATS_PAGES), max_workers, words)
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
    search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query, "count": min(max(limit, 1), 8), "setlang": "ru"})
    request = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read().decode("utf-8", "ignore")
    parser = _BingParser()
    parser.feed(data)
    results, seen = [], set()
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
