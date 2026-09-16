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


def _fetch_page(url: str, max_chars: int = 7000) -> str:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type.lower():
                return ""
            data = response.read(1_500_000).decode("utf-8", "ignore")
        parser = _TextParser()
        parser.feed(data)
        text = " ".join(parser.parts)
        return text[:max_chars]
    except Exception:
        return ""



COMEBACK_CATS_URL = "https://comeback.pw/cats/136/"


def search_comeback_cats(query: str, max_chars: int = 12000) -> str:
    """Use the fixed ComebackPW category page as a primary game-market source."""
    page_text = _fetch_page(COMEBACK_CATS_URL, max_chars=max_chars)
    if not page_text:
        return ""
    return (
        "Источник: ComebackPW — База котов (категория 136)\\n"
        f"URL: {COMEBACK_CATS_URL}\\n"
        f"Запрос: {query.strip()}\\n"
        f"Содержимое страницы:\\n{page_text}"
    )


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
        page_text = _fetch_page(url)
        if page_text:
            results.append(f"Источник: {title}\nURL: {url}\nСодержимое:\n{page_text}")
        else:
            results.append(f"Источник: {title}\nURL: {url}")
        if len(results) >= limit:
            break

    return "\n\n---\n\n".join(results)
