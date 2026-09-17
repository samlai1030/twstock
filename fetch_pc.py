"""Runs ON SAM'S WINDOWS PC (the devserver has no external egress; the PC does).

Pulls Taiwan market history date-by-date into C:\\myclaw_tw\\raw\\ as gzipped JSON.

Threading: one worker per FEED, not per date. Each worker keeps its own ~3s
pacing, so we never exceed ~1 req/s against TWSE overall while still cutting
wall-clock ~3x (the bottleneck is per-request latency, not our sleep). Any 429 /
error escalates that worker's delay and it retries -- we back off, never hammer.

Resumable: existing files are skipped, so it is safe to kill and relaunch.
"""
import urllib.request, urllib.error, json, ssl, time, os, gzip, threading
import datetime as dt

OUT = r"C:\myclaw_tw\raw"
PROG = r"C:\myclaw_tw\progress.txt"
os.makedirs(OUT, exist_ok=True)

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

FEEDS = {
    "mi_index": "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json",
    "t86":      "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType=ALLBUT0999&response=json",
    "margin":   "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=ALL&response=json",
}
START, END = dt.date(2025, 2, 1), dt.date(2026, 8, 15)
BASE_SLEEP = 3.0

lock = threading.Lock()


def note(msg):
    with lock:
        with open(PROG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def worker(name, tmpl):
    delay = BASE_SLEEP
    d, nfile, nday = START, 0, 0
    while d <= END:
        if d.weekday() >= 5:
            d += dt.timedelta(days=1); continue
        ds = d.strftime("%Y%m%d")
        path = os.path.join(OUT, "%s_%s.json.gz" % (name, ds))
        if os.path.exists(path):
            d += dt.timedelta(days=1); continue
        nday += 1
        ok = False
        for attempt in range(5):
            try:
                r = urllib.request.urlopen(urllib.request.Request(tmpl.format(d=ds), headers=UA),
                                           timeout=75, context=CTX)
                j = json.loads(r.read().decode("utf-8"))
                if isinstance(j, dict) and j.get("stat") == "OK":
                    with gzip.open(path, "wt", encoding="utf-8") as f:
                        json.dump(j, f, ensure_ascii=False)
                    nfile += 1
                ok = True
                delay = max(BASE_SLEEP, delay * 0.9)      # recover pacing slowly
                break
            except Exception as e:
                code = getattr(e, "code", None)
                delay = min(30.0, delay * (2.0 if code == 429 else 1.4))
                note("  %s %s retry%d %s delay=%.1f" % (name, ds, attempt, type(e).__name__, delay))
                time.sleep(delay)
        if not ok:
            note("  %s %s GAVE UP" % (name, ds))
        if nday % 25 == 0:
            note("  %-8s ...%s days=%d files=%d delay=%.1f" % (name, ds, nday, nfile, delay))
        time.sleep(delay)
        d += dt.timedelta(days=1)
    note("FEED DONE %s days=%d files=%d" % (name, nday, nfile))


note("START(threaded) %s" % dt.datetime.now())
ths = [threading.Thread(target=worker, args=(n, u), daemon=False) for n, u in FEEDS.items()]
[t.start() for t in ths]
[t.join() for t in ths]
note("ALL DONE %s" % dt.datetime.now())
