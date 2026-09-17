"""Second PC-side pull: ex-dividend/ex-rights events + listed-company master.

Ex-rights matters more than it sounds. TWSE close prices are UNADJUSTED, and
Taiwan pays most dividends Jul-Sep -- right inside the backtest window. Without
adjustment a 4% yield looks like a 4% one-day crash, which both understates
returns and trips stop-losses that never would have fired in reality.
"""
import urllib.request, json, ssl, time, os, gzip

OUT = r"C:\myclaw_tw\raw"
os.makedirs(OUT, exist_ok=True)
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def get(url, tries=4):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90, context=CTX)
            return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                return {"__error__": "%s %s" % (type(e).__name__, str(e)[:100])}
            time.sleep(5 * (i + 1))


jobs = {
    # 除權除息計算結果表 - one ranged query covers the whole window
    "exright": "https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20250201&endDate=20260815&response=json",
}
for name, url in jobs.items():
    j = get(url)
    p = os.path.join(OUT, "%s.json.gz" % name)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)
    n = len(j.get("data") or (j.get("tables") or [{}])[0].get("data", []) if isinstance(j, dict) else [])
    print(name, "stat=", (j or {}).get("stat"), "rows=", n)
    time.sleep(3)
