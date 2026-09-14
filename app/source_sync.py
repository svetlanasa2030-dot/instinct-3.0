import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from .knowledge import KNOWLEDGE_DIR

class _P(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            h=dict(attrs).get('href')
            if h: self.links.append(h)
    def handle_data(self,data): self.text.append(data)

def collect_sources(sources, max_pages=500):
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    total=0
    for root in sources:
        root=root.strip().rstrip('/')
        p=urllib.parse.urlparse(root)
        if p.scheme not in ('http','https') or not p.netloc: continue
        domain=p.netloc.lower(); queue=[root]; seen=set(); pages=[]
        while queue and len(pages)<max_pages:
            url=queue.pop(0).split('#')[0]
            if url in seen: continue
            seen.add(url)
            q=urllib.parse.urlparse(url)
            if q.netloc.lower()!=domain: continue
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req,timeout=15) as r:
                    if 'text/html' not in r.headers.get('Content-Type','').lower(): continue
                    html=r.read(1500000).decode('utf-8','ignore')
                parser=_P(); parser.feed(html)
                text=re.sub(r'\\s+',' ',' '.join(parser.text)).strip()
                if text: pages.append((url,text[:30000]))
                for h in parser.links:
                    u=urllib.parse.urljoin(url,h).split('#')[0]
                    if urllib.parse.urlparse(u).netloc.lower()==domain and u not in seen: queue.append(u)
            except Exception:
                continue
        name=re.sub(r'[^a-zA-Z0-9_-]+','_',domain)+'.md'
        out=KNOWLEDGE_DIR/name
        out.write_text('\n\n---\n\n'.join(f'URL: {u}\n{t}' for u,t in pages),encoding='utf-8')
        total+=len(pages)
    return total
