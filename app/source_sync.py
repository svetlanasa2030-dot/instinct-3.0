import re
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .knowledge import KNOWLEDGE_DIR

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"

class _P(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.text=[]
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag=="a" and d.get("href"): self.links.append(d["href"])
    def handle_data(self, data): self.text.append(data)

def normalize_url(url):
    url=url.strip()
    if url and not re.match(r"^https?://", url, re.I):
        url="https://"+url
    return url.rstrip("/")

def _fetch(url, accept="*/*"):
    req=urllib.request.Request(normalize_url(url), headers={"User-Agent":UA,"Accept":accept,"Accept-Language":"ru,en;q=0.8"})
    return urllib.request.urlopen(req, timeout=20)

def _xml_urls(data, base):
    urls=[]
    try:
        root=ET.fromstring(data.decode("utf-8","ignore"))
        for el in root.iter():
            tag=el.tag.lower().split("}")[-1]
            if tag=="loc" and el.text:
                urls.append(urllib.parse.urljoin(base, el.text.strip()))
    except Exception:
        pass
    return urls

def find_sitemaps(root):
    root=normalize_url(root)
    p=urllib.parse.urlparse(root)
    if p.scheme not in ("http","https") or not p.netloc:
        raise ValueError("Введите адрес сайта, например: https://comeback.pw")
    candidates=[]
    try:
        with _fetch(urllib.parse.urljoin(root+"/","robots.txt"),"text/plain,*/*;q=0.5") as r:
            robots=r.read(500000).decode("utf-8","ignore")
        for line in robots.splitlines():
            if line.lower().startswith("sitemap:"):
                candidates.append(line.split(":",1)[1].strip())
    except Exception:
        pass
    for path in ("/sitemap.xml","/sitemap_index.xml","/sitemap-index.xml",
                 "/sitemap.php","/sitemap1.xml","/sitemap_index.xml.gz"):
        candidates.append(urllib.parse.urljoin(root+"/",path))
    found=[]
    for u in dict.fromkeys(candidates):
        try:
            with _fetch(u,"application/xml,text/xml,*/*;q=0.8") as r:
                data=r.read(5000000)
            # A valid XML sitemap must expose at least one loc.
            if _xml_urls(data,u):
                found.append(u)
        except Exception:
            continue
    return list(dict.fromkeys(found))

def _same_domain(u, domain):
    return urllib.parse.urlparse(u).netloc.lower()==domain

def collect_sources(sources, max_pages=500, sitemap=None):
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    total=0
    for root in sources:
        root=normalize_url(root)
        p=urllib.parse.urlparse(root)
        if p.scheme not in ("http","https") or not p.netloc:
            continue
        domain=p.netloc.lower()
        queue=[]
        if sitemap:
            for u in _xml_urls(_fetch(sitemap,"application/xml,text/xml,*/*;q=0.8").read(5000000), sitemap):
                if _same_domain(u,domain): queue.append(u)
        if not queue:
            found=find_sitemaps(root)
            for sm in found:
                try:
                    with _fetch(sm,"application/xml,text/xml,*/*;q=0.8") as r: data=r.read(5000000)
                    for u in _xml_urls(data,sm):
                        if _same_domain(u,domain): queue.append(u)
                except Exception:
                    pass
        if not queue:
            queue=[root]
        seen=set(); pages=[]
        while queue and len(pages)<max_pages:
            url=queue.pop(0).split("#")[0]
            if url in seen or not _same_domain(url,domain): continue
            seen.add(url)
            try:
                with _fetch(url,"text/html,application/xhtml+xml,*/*;q=0.8") as r:
                    ctype=r.headers.get("Content-Type","").lower()
                    if "html" not in ctype: continue
                    html=r.read(1500000).decode("utf-8","ignore")
                parser=_P(); parser.feed(html)
                text=re.sub(r"\s+"," "," ".join(parser.text)).strip()
                if text: pages.append((url,text[:30000]))
                for h in parser.links:
                    u=urllib.parse.urljoin(url,h).split("#")[0]
                    if _same_domain(u,domain) and u not in seen: queue.append(u)
            except Exception:
                continue
        name=re.sub(r"[^a-zA-Z0-9_-]+","_",domain)+".md"
        (KNOWLEDGE_DIR/name).write_text("\n\n---\n\n".join(f"URL: {u}\n{t}" for u,t in pages),encoding="utf-8")
        total+=len(pages)
    return total
