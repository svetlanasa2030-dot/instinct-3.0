import re, sqlite3, urllib.parse, urllib.request
from html.parser import HTMLParser

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

def crawl(root_url, db_path, max_pages=10000):
    root_url=root_url.strip().rstrip("/")
    p=urllib.parse.urlparse(root_url)
    if p.scheme not in ("http","https") or not p.netloc: raise ValueError("Некорректный URL")
    domain=p.netloc.lower(); queue=[root_url]; seen=set(); count=0
    db=sqlite3.connect(db_path)
    db.execute("CREATE TABLE IF NOT EXISTS web_pages(url TEXT PRIMARY KEY,title TEXT,content TEXT,updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    while queue and count<max_pages:
        url=queue.pop(0)
        if url in seen: continue
        seen.add(url)
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"InstinctBot/3.0"})
            with urllib.request.urlopen(req,timeout=15) as r:
                if "text/html" not in r.headers.get("Content-Type",""): continue
                raw=r.read(2000000)
            html=raw.decode("utf-8","ignore")
            parser=_Parser(); parser.feed(html)
            content=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html)).strip()
            db.execute("INSERT OR REPLACE INTO web_pages(url,title,content) VALUES(?,?,?)",(url,"".join(parser.title).strip(),content[:100000]))
            count+=1
            for href in parser.links:
                nxt=urllib.parse.urljoin(url,href).split("#")[0]
                q=urllib.parse.urlparse(nxt)
                if q.scheme in ("http","https") and q.netloc.lower()==domain and nxt not in seen:
                    queue.append(nxt)
            db.commit()
        except Exception: continue
    db.close(); return count
