"""PC-side news collector for the watchlist / current holdings.

IMPORTANT SCOPE NOTE: this feeds the *live* information panel only. It is NOT a
backtest signal. Historical headline archives are not reliably timestamped to
the minute, and scoring past news with today's sentiment model is textbook
look-ahead bias -- it would inflate the backtest and teach us nothing. So news
informs the human's weekly review; the simulated track record never touches it.

Sources are public RSS/JSON, no key required.
"""
import urllib.request, json, ssl, time, os, gzip, re
import xml.etree.ElementTree as ET

OUT = r"C:\myclaw_tw"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

FEEDS = [
    ("cnyes_tw",  "https://news.cnyes.com/rss/v1/news/category/tw_stock"),
    ("cnyes_hot", "https://news.cnyes.com/rss/v1/news/category/headline"),
    ("yahoo_tw",  "https://tw.stock.yahoo.com/rss?category=news"),
    ("moneydj",   "https://www.moneydj.com/kmdj/rss/rsslist.aspx?svc=NW&fno=1"),
]


def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45, context=CTX)
            return r.read()
        except Exception as e:
            if i == tries - 1:
                return None
            time.sleep(3 * (i + 1))


def parse_rss(b):
    out = []
    try:
        root = ET.fromstring(b)
    except Exception:
        return out
    for it in root.iter():
        if not it.tag.endswith("item"):
            continue
        g = lambda t: next((c.text or "" for c in it if c.tag.endswith(t)), "")
        out.append(dict(title=g("title").strip(), link=g("link").strip(),
                        pub=g("pubDate").strip(), desc=re.sub(r"<[^>]+>", "", g("description") or "")[:300]))
    return out


items = []
for name, url in FEEDS:
    b = get(url)
    if not b:
        print(name, "FAIL"); continue
    got = parse_rss(b)
    for it in got:
        it["src"] = name
    items += got
    print(name, "items=", len(got))
    time.sleep(2)

with gzip.open(os.path.join(OUT, "news.json.gz"), "wt", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False)
print("TOTAL", len(items))
