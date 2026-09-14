import re
import urllib.parse
import urllib.request
import urllib.error
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .knowledge import KNOWLEDGE_DIR

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"

class _P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "a" and d.get("href"):
            self.links.append(d["href"])
    def handle_data(self, data):
        self.text.append(data)

def normalize_url(url):
    url = url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url.rstrip("/")

def _fetch(url, accept="*/*", retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                normalize_url(url),
                headers={
                    "User-Agent": UA,
                    "Accept": accept,
                    "Accept-Language": "ru,en;q=0.8",
                    "Connection": "close",
                },
            )
            return urllib.request.urlopen(req, timeout=30)
        except Exception as e:
            last = e
            if attempt + 1 < retries:
                time.sleep(0.8 * (attempt + 1))
    raise last

def _xml_urls(data, base):
    urls = []
    try:
        root = ET.fromstring(data.decode("utf-8", "ignore"))
        for el in root.iter():
            tag = el.tag.lower().split("}")[-1]
            if tag == "loc" and el.text:
                urls.append(urllib.parse.urljoin(base, el.text.strip()))
    except Exception:
        pass
    return urls

def find_sitemaps(root):
    root = normalize_url(root)
    p = urllib.parse.urlparse(root)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("Введите адрес сайта, например: https://comeback.pw")
    candidates = []
    try:
        with _fetch(urllib.parse.urljoin(root + "/", "robots.txt"), "text/plain,*/*;q=0.5") as r:
            robots = r.read(500000).decode("utf-8", "ignore")
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())
    except Exception:
        pass
    for path in (
        "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
        "/sitemap.php", "/sitemap1.xml", "/sitemap_index.xml.gz"
    ):
        candidates.append(urllib.parse.urljoin(root + "/", path))
    found = []
    for u in dict.fromkeys(candidates):
        try:
            with _fetch(u, "application/xml,text/xml,*/*;q=0.8") as r:
                data = r.read(10000000)
            urls = _xml_urls(data, u)
            if urls:
                found.append(u)
        except Exception:
            continue
    return list(dict.fromkeys(found))

def _same_domain(u, domain):
    return urllib.parse.urlparse(u).netloc.lower() == domain

def _looks_like_forum(root):
    host = urllib.parse.urlparse(root).netloc.lower()
    return "forum." in host or "/forum" in urllib.parse.urlparse(root).path.lower()

def _priority(url, forum=False):
    path = urllib.parse.urlparse(url).path.lower()
    score = 0
    if forum:
        if "/threads/" in path: score += 100
        if "/page-" in path: score += 80
        if "/forums/" in path: score += 50
        if "/categories/" in path: score += 20
    return score

def collect_sources(sources, max_pages=20000, progress=None):
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    total = 0
    results = []
    for root in sources:
        root = normalize_url(root)
        p = urllib.parse.urlparse(root)
        if p.scheme not in ("http", "https") or not p.netloc:
            results.append((root, 0, "Некорректный URL"))
            continue
        domain = p.netloc.lower()
        forum = _looks_like_forum(root)
        queue = []
        errors = 0
        found_sitemaps = find_sitemaps(root)
        for sm in found_sitemaps:
            try:
                with _fetch(sm, "application/xml,text/xml,*/*;q=0.8") as r:
                    data = r.read(10000000)
                for u in _xml_urls(data, sm):
                    if _same_domain(u, domain):
                        queue.append(u)
            except Exception:
                pass
        queue.append(root)
        seen = set()
        pages = []
        queued = set(queue)

        while queue and len(pages) < max_pages:
            queue.sort(key=lambda u: _priority(u, forum), reverse=True)
            url = queue.pop(0).split("#")[0]
            if url in seen or not _same_domain(url, domain):
                continue
            seen.add(url)
            try:
                with _fetch(url, "text/html,application/xhtml+xml,*/*;q=0.8") as r:
                    ctype = r.headers.get("Content-Type", "").lower()
                    if "html" not in ctype:
                        continue
                    html = r.read(2500000).decode("utf-8", "ignore")
                parser = _P()
                parser.feed(html)
                text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
                if text:
                    pages.append((url, text[:50000]))
                for h in parser.links:
                    u = urllib.parse.urljoin(url, h).split("#")[0]
                    q = urllib.parse.urlparse(u)
                    if q.scheme in ("http", "https") and _same_domain(u, domain) and u not in seen and u not in queued:
                        queued.add(u)
                        queue.append(u)
                if progress:
                    progress(root, len(pages), len(seen), len(queue), None, url)
            except Exception as e:
                errors += 1
                if progress:
                    progress(root, len(pages), len(seen), len(queue), str(e), url)

        name = re.sub(r"[^a-zA-Z0-9_-]+", "_", domain) + ".md"
        header = f"# {root}\n# Тип: {'форум' if forum else 'сайт'}\n# Загружено страниц: {len(pages)}\n\n"
        (KNOWLEDGE_DIR / name).write_text(
            header + "\n\n---\n\n".join(f"URL: {u}\n{t}" for u, t in pages),
            encoding="utf-8",
        )
        total += len(pages)
        results.append((root, len(pages), f"ошибок загрузки: {errors}"))
        if progress:
            progress(root, len(pages), len(seen), len(queue), None)

    return total, results

def scan_pages_sequential(urls, progress=None, google_webhook=""):
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    total = len(urls)
    done = 0
    out = KNOWLEDGE_DIR / "manual_pages.md"
    with out.open("a", encoding="utf-8") as f:
        for url in urls:
            url = normalize_url(url)
            try:
                with _fetch(url, "text/html,application/xhtml+xml,*/*;q=0.8") as r:
                    html = r.read(2000000).decode("utf-8", "ignore")
                parser = _P()
                parser.feed(html)
                text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
                if text:
                    f.write(f"\n\n## {url}\n\n{text[:50000]}\n")
                    if google_webhook:
                        from .knowledge import append_to_google_docs
                        append_to_google_docs(google_webhook, url, text[:50000])
                    done += 1
            except Exception as e:
                f.write(f"\n\n## {url}\n\n[Ошибка загрузки: {e}]\n")
            if progress:
                progress(done, total)
    return done
