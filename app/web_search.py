import concurrent.futures
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser


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
            if "text/html" not in content_type.lower():
                return ""
            data = response.read(2_000_000).decode("utf-8", "ignore")
        parser = _TextParser()
        parser.feed(data)
        text = " ".join(parser.parts)
        return text[:max_chars]
    except Exception:
        return ""


COMEBACK_CATS_BASE = "https://comeback.pw/cats/146/"
COMEBACK_CATS_PAGES = 410


def _query_words(query: str) -> list[str]:
    words = re.findall(r"[\wа-яА-ЯёЁ-]{2,}", query.lower())
    # Remove common Russian request words. They do not help find a cat row
    # and otherwise produce many false-positive pages.
    stop_words = {
        "где", "найти", "найди", "есть", "мне", "нужен", "нужна", "нужно",
        "можно", "можно", "как", "какой", "какая", "какие", "покажи", "покажите",
        "координаты", "координата", "кот", "кота", "коте", "котом", "локация",
        "место", "месте", "цена", "стоимость", "продажа", "покупка",
    }
    return [w for w in words if w not in stop_words]


def _find_matches(page: int, query_words: list[str]) -> str:
    url = COMEBACK_CATS_BASE + "?page=" + str(page)
    text = _fetch_page(url)
    if not text:
        return ""

    normalized = text.lower()
    if not query_words:
        return ""

    hits = [word for word in query_words if word in normalized]
    if not hits:
        return ""

    # Return focused fragments instead of the whole page. This keeps the AI
    # context small while preserving the NPC/player, prices and coordinates
    # located near the matching cat name.
    fragments = []
    used_ranges = []
    for word in hits:
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
        f"Совпадения: {', '.join(sorted(set(hits)))}\n"
        f"Фрагменты:\n" + "\n---\n".join(fragments)
    )


def search_comeback_cats(query: str, max_pages: int = COMEBACK_CATS_PAGES, max_workers: int = 12) -> str:
    """Search all 410 pages of the ComebackPW cat database in parallel."""
    query = query.strip()
    if not query:
        return ""

    words = _query_words(query)
    if not words:
        return ""

    # The database currently has 410 pages. Fetch pages concurrently so a
    # search does not wait for 410 sequential network requests.
    pages = range(1, min(max_pages, COMEBACK_CATS_PAGES) + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda page: _find_matches(page, words), pages))

    matches = [result for result in results if result]
    return "\n\n---\n\n".join(matches[:12])


def search_web(query: str, limit: int = 5) -> str:
    """Search the public web with Bing and read the relevant pages."""
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
