#!/usr/bin/env python3
"""Parse the PC-fetched TWSE JSON dump into a tidy SQLite DB.

Tables
  price(date, code, name, open, high, low, close, volume, turnover, trades)
  chip (date, code, foreign_net, trust_net, dealer_net, total_net)   [shares]
  margin(date, code, margin_bal, short_bal)                          [lots]
  exright(date, code, prev_close, ref_price, cash_div, ...)

Everything is stored RAW (unadjusted). Dividend adjustment happens in the
strategy layer via a back-adjust factor, so the raw record stays auditable.
"""
import gzip, json, os, re, sqlite3, sys, glob

RAW = sys.argv[1] if len(sys.argv) > 1 else "raw"
DB = sys.argv[2] if len(sys.argv) > 2 else "twstock.db"

NUM = re.compile(r"^-?[\d,]+(\.\d+)?$")


def num(s):
    """TWSE emits '1,234', '--', '', 'X' and HTML blobs. Anything not numeric -> None."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "--", "-", "X", "N/A", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick_table(j, must_have, min_cols):
    """Find the table whose header contains all `must_have` strings.

    Table ORDER in MI_INDEX is not stable across dates, so never index by
    position -- match on the header text instead.
    """
    tabs = j.get("tables")
    if tabs is None:
        tabs = [j] if j.get("fields") else []
    for t in tabs:
        f = t.get("fields") or []
        if len(f) >= min_cols and all(any(m in c for c in f) for m in must_have):
            return t
    return None


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("""
    DROP TABLE IF EXISTS price; DROP TABLE IF EXISTS chip;
    DROP TABLE IF EXISTS margin; DROP TABLE IF EXISTS exright;
    CREATE TABLE price(date TEXT, code TEXT, name TEXT, open REAL, high REAL,
                       low REAL, close REAL, volume REAL, turnover REAL, trades REAL,
                       PRIMARY KEY(date,code));
    CREATE TABLE chip(date TEXT, code TEXT, foreign_net REAL, trust_net REAL,
                      dealer_net REAL, total_net REAL, PRIMARY KEY(date,code));
    CREATE TABLE margin(date TEXT, code TEXT, margin_bal REAL, short_bal REAL,
                        PRIMARY KEY(date,code));
    CREATE TABLE exright(date TEXT, code TEXT, prev_close REAL, ref_price REAL,
                         cash_div REAL, PRIMARY KEY(date,code));
    """)

    def d8(fn):
        m = re.search(r"_(\d{8})\.json\.gz$", fn)
        return "%s-%s-%s" % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:]) if m else None

    # ---- prices -------------------------------------------------------
    n = 0
    for fn in sorted(glob.glob(os.path.join(RAW, "mi_index_*.json.gz"))):
        date = d8(fn)
        j = json.load(gzip.open(fn, "rt", encoding="utf-8"))
        t = pick_table(j, ["證券代號", "收盤價", "成交金額"], 14)
        if not t:
            continue
        f = t["fields"]
        ix = {k: next(i for i, c in enumerate(f) if k in c)
              for k in ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額",
                        "開盤價", "最高價", "最低價", "收盤價"]}
        rows = []
        for r in t["data"]:
            c = str(r[ix["證券代號"]]).strip()
            cl = num(r[ix["收盤價"]])
            if cl is None:
                continue                      # no trade that day
            rows.append((date, c, str(r[ix["證券名稱"]]).strip(),
                         num(r[ix["開盤價"]]), num(r[ix["最高價"]]), num(r[ix["最低價"]]), cl,
                         num(r[ix["成交股數"]]), num(r[ix["成交金額"]]), num(r[ix["成交筆數"]])))
        cur.executemany("INSERT OR REPLACE INTO price VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        n += len(rows)
    print("price rows:", n)

    # ---- chips (three institutions) ------------------------------------
    # Column order verified arithmetically on a live file:
    #   idx4 foreign(ex-dealer) + idx7 foreign-dealer + idx10 trust + idx11 dealer == idx18 total
    n = 0
    for fn in sorted(glob.glob(os.path.join(RAW, "t86_*.json.gz"))):
        date = d8(fn)
        j = json.load(gzip.open(fn, "rt", encoding="utf-8"))
        f = j.get("fields") or []
        if len(f) < 12:
            continue
        rows = []
        for r in j.get("data", []):
            if len(f) >= 19:
                fgn = (num(r[4]) or 0) + (num(r[7]) or 0)
                tru, dlr, tot = num(r[10]), num(r[11]), num(r[18])
            else:                              # older 12-col layout
                fgn, tru, dlr, tot = num(r[2]), num(r[5]), num(r[8]), num(r[11])
            rows.append((date, str(r[0]).strip(), fgn, tru, dlr, tot))
        cur.executemany("INSERT OR REPLACE INTO chip VALUES(?,?,?,?,?,?)", rows)
        n += len(rows)
    print("chip rows:", n)

    # ---- margin / short balances ---------------------------------------
    n = 0
    for fn in sorted(glob.glob(os.path.join(RAW, "margin_*.json.gz"))):
        date = d8(fn)
        j = json.load(gzip.open(fn, "rt", encoding="utf-8"))
        t = pick_table(j, ["代號", "今日餘額"], 14)
        if not t:
            continue
        f = t["fields"]
        bal = [i for i, c in enumerate(f) if "今日餘額" in c]   # [0]=融資 [1]=融券
        if len(bal) < 2:
            continue
        rows = [(date, str(r[0]).strip(), num(r[bal[0]]), num(r[bal[1]]))
                for r in t["data"]]
        cur.executemany("INSERT OR REPLACE INTO margin VALUES(?,?,?,?)", rows)
        n += len(rows)
    print("margin rows:", n)

    # ---- ex-dividend / ex-rights ---------------------------------------
    exfiles = sorted(glob.glob(os.path.join(RAW, "exright*.json.gz")))
    for fn in exfiles:
        j = json.load(gzip.open(fn, "rt", encoding="utf-8"))
        t = pick_table(j, ["股票代號"], 5) or (j if j.get("fields") else None)
        if t:
            f = t["fields"]

            def find(*keys):
                for k in keys:
                    for i, c in enumerate(f):
                        if k in c:
                            return i
                return None
            i_dt, i_cd = find("資料日期", "除權息日期"), find("股票代號")
            i_pv, i_rf = find("除權息前收盤價"), find("除權息參考價")
            i_cash = find("權值+息值", "息值")
            rows = []
            for r in t.get("data", []):
                raw = str(r[i_dt]).strip()
                m = re.match(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日", raw)
                if m:                          # ROC calendar -> ISO
                    date = "%04d-%02d-%02d" % (int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
                else:
                    p = raw.replace("/", "-").split("-")
                    if len(p) != 3:
                        continue
                    y = int(p[0]);  y += 1911 if y < 1911 else 0
                    date = "%04d-%02d-%02d" % (y, int(p[1]), int(p[2]))
                rows.append((date, str(r[i_cd]).strip(), num(r[i_pv]), num(r[i_rf]),
                             num(r[i_cash]) if i_cash is not None else None))
            cur.executemany("INSERT OR REPLACE INTO exright VALUES(?,?,?,?,?)", rows)
            print("exright rows:", len(rows), "from", os.path.basename(fn))
    if not exfiles:
        print("exright: MISSING (dividend adjustment will be skipped)")

    cur.executescript("""
    CREATE INDEX i_p_code ON price(code); CREATE INDEX i_p_date ON price(date);
    CREATE INDEX i_c_code ON chip(code);  CREATE INDEX i_m_code ON margin(code);
    """)
    con.commit()
    for t in ("price", "chip", "margin", "exright"):
        c = cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM %s" % t).fetchone()
        print("  %-8s n=%-8s %s .. %s" % (t, c[0], c[1], c[2]))
    con.close()


main()
