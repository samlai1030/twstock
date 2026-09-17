#!/usr/bin/env python3
"""Cloud/CI counterpart of the PC market-data fetcher.

Downloads raw TWSE JSON responses and saves each response body VERBATIM as
raw/{prefix}_{YYYYMMDD}.json.gz -- the exact format build_db.py consumes
(it finds tables by header text itself, so this script never parses rows).

Feeds (all public, no API key):
  MI_INDEX : whole-market daily OHLCV / turnover   -> mi_index_{date}.json.gz
  T86      : institutional investors buy/sell      -> t86_{date}.json.gz
  MI_MARGN : margin / short balances               -> margin_{date}.json.gz
  TWT49U   : ex-right / ex-dividend reference      -> exright_{date}.json.gz

Incremental: files already present in raw/ are skipped, so a warm
actions/cache only fetches the last few trading days.

Fail-closed: a date that does not come back as parseable JSON with a data
payload (holidays, TWSE hiccups) is skipped, not saved. The workflow's
sanity gate after build_db.py decides whether coverage is good enough to
publish; if not, the job fails and the previously published dashboard
stays live untouched.

Stdlib only (urllib). Be polite: ~1s between requests, 3 retries.
"""

import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.request
import urllib.error

RAW = os.environ.get("RAW_DIR", "raw")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "400"))
DELAY = float(os.environ.get("FETCH_DELAY", "0.8"))
RETRIES = 3
TIMEOUT = 30
UA = {"User-Agent": "twstock-ci-dashboard/1.0 (github-actions; contact: repo owner)"}

FEEDS = [
    ("mi_index",
     "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALL"),
    ("t86",
     "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType=ALL"),
    ("margin",
     "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=MS"),
    ("exright",
     "https://www.twse.com.tw/rwd/zh/afterTrading/TWT49U?date={d}"),
]


def has_payload(obj):
    """True when the TWSE body actually carries table data."""
    if not isinstance(obj, dict):
        return False
    if obj.get("data"):
        return True
    for t in obj.get("tables") or []:
        if isinstance(t, dict) and t.get("data"):
            return True
    return False


def fetch(url):
    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read()
            if resp.status != 200:
                raise urllib.error.HTTPError(url, resp.status, "bad status",
                                            None, None)
            return body
        except Exception as e:  # noqa: BLE001 - retry then skip the date
            last = e
            time.sleep(2 ** attempt)
    print(f"    give up: {last}", flush=True)
    return None


def main():
    os.makedirs(RAW, exist_ok=True)
    today = dt.date.today()
    # Yesterday at the latest: today's session may not be published yet.
    dates = [(today - dt.timedelta(days=i)).strftime("%Y%m%d")
             for i in range(1, LOOKBACK_DAYS + 1)]
    saved, skipped, existed = 0, 0, 0
    for d in dates:
        for prefix, tmpl in FEEDS:
            fn = os.path.join(RAW, f"{prefix}_{d}.json.gz")
            if os.path.exists(fn):
                existed += 1
                continue
            body = fetch(tmpl.format(d=d))
            time.sleep(DELAY)
            if body is None:
                skipped += 1
                continue
            try:
                obj = json.loads(body.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                skipped += 1
                continue
            if not has_payload(obj):
                skipped += 1  # holiday or empty session: leave no file
                continue
            with gzip.open(fn, "wt", encoding="utf-8") as f:
                f.write(body.decode("utf-8", "replace"))
            saved += 1
    print(f"fetch_ci: saved={saved} skipped={skipped} already_cached={existed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
