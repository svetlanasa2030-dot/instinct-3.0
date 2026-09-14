import urllib.parse
from .web_crawler import _fetch

def discover_public_sources(root):
    root=root.rstrip('/')
    found=[]
    try:
        with _fetch(root+'/robots.txt','text/plain,*/*;q=0.5') as r:
            for line in r.read(500000).decode('utf-8','ignore').splitlines():
                if line.lower().startswith('sitemap:'):
                    found.append(line.split(':',1)[1].strip())
    except Exception:
        pass
    for path in ('/sitemap.xml','/sitemap_index.xml','/sitemap-index.xml','/sitemap.php','/rss.xml','/feed','/atom.xml'):
        found.append(urllib.parse.urljoin(root+'/',path))
    return list(dict.fromkeys(found))
