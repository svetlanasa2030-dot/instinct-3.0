import re, sqlite3, urllib.parse, urllib.request, urllib.error
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]; self.title=[]; self.in_title=False
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag=="a" and d.get("href"): self.links.append(d["href"])
        if tag=="title": self.in_title=True
    def handle_endtag(self, tag):
        if tag=="title": self.in_title=False
    def handle_data(self, data):
        if self.in_title: self.title.append(data)

def _fetch(url):
    req=urllib.request.Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"ru,en;q=0.8",
    })
    return urllib.request.urlopen(req,timeout=20)

def _sitemap_urls(root):
    urls=[]
    for path in ("/sitemap.xml","/sitemap_index.xml","/sitemap.php","/sitemap-index.xml"):
        try:
            with _fetch(urllib.parse.urljoin(root+"/",path)) as r:
                data=r.read(5_000_000)
            text=data.decode("utf-8","ignore")
            root_xml=ET.fromstring(text)
            for el in root_xml.iter():
                if el.tag.lower().endswith("loc") and el.text:
                    urls.append(el.text.strip())
        except Exception:
            pass
    return urls

def crawl(root_url, db_path, max_pages=10000):
    # Discover public sitemap/feed endpoints before normal same-domain traversal.
    try:
        from .public_sources import discover_public_sources
        public_sources = discover_public_sources(root_url)
    except Exception:
        public_sources = []
    root_url=root_url.strip().rstrip("/")
    p=urllib.parse.urlparse(root_url)
    if p.scheme not in ("http","https") or not p.netloc:
        raise ValueError("Некорректный URL")
    domain=p.netloc.lower()
    queue=[root_url]
    for source in public_sources:
        try:
            with _fetch(source) as r:
                data=r.read(5000000).decode("utf-8","ignore")
            try:
                xml=ET.fromstring(data)
                for el in xml.iter():
                    if el.tag.lower().endswith("loc") and el.text:
                        u=el.text.strip()
                        if urllib.parse.urlparse(u).netloc.lower()==domain: queue.append(u)
            except Exception:
                pass
        except Exception:
            pass
    queue.extend(_sitemap_urls(root_url))
    seen=set(); count=0; last_error=None
    db=sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS web_pages(url TEXT PRIMARY KEY,title TEXT,content TEXT,updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    while queue and count<max_pages:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url)
        q0=urllib.parse.urlparse(url)
        if q0.netloc.lower()!=domain: continue
        try:
            with _fetch(url) as r:
                content_type=r.headers.get("Content-Type","").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    continue
                raw=r.read(2_000_000)
            html=raw.decode("utf-8","ignore")
            parser=_Parser(); parser.feed(html)
            content=re.sub(r"\s+"," ",re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>|<[^>]+>"," ",html,flags=re.I|re.S)).strip()
            db.execute(
                "INSERT OR REPLACE INTO web_pages(url,title,content,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",
                (url,"".join(parser.title).strip(),content[:100000])
            )
            count+=1
            for href in parser.links:
                nxt=urllib.parse.urljoin(url,href).split("#")[0]
                q=urllib.parse.urlparse(nxt)
                if q.scheme in ("http","https") and q.netloc.lower()==domain and nxt not in seen:
                    queue.append(nxt)
            db.commit()
        except urllib.error.HTTPError as e:
            last_error=f"HTTP {e.code} для {url}"
        except Exception as e:
            last_error=f"{type(e).__name__}: {e}"
    db.close()
    if count==0 and last_error:
        raise RuntimeError(last_error)
    return count
