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


def search_forum(forum_url: str, query: str, limit: int = 5) -> str:
    """Search the configured forum through Bing site search."""
    host = urllib.parse.urlparse(forum_url.strip()).netloc.lower()
    if not host:
        return ""

    search_url = "https://www.bing.com/search?" + urllib.parse.urlencode({
        "q": f"site:{host} {query}",
        "count": min(max(limit, 1), 10),
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
    for title, url in parser.results:
        if urllib.parse.urlparse(url).netloc.lower() == host:
            results.append(f"Тема: {title}\nURL: {url}")
        if len(results) >= limit:
            break

    return "\n\n---\n\n".join(results)
