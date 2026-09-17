#!/usr/bin/env python3
"""集保戶股權分散表 (TDCC shareholder-dispersion) archiver + 籌碼集中度 metrics.

WHY THIS EXISTS AS A SEPARATE DB
--------------------------------
`twstock.db` is REBUILT FROM SCRATCH every night (`build_db.py raw twstock_new.db`
then `mv` over the old one). Anything written into it is destroyed daily. The TDCC
feed serves **only the latest weekly snapshot** -- there is no history endpoint and
no way to backfill -- so the archive is append-only and irreplaceable. It therefore
lives in its own `tdcc.db`, which nothing else ever overwrites.

Losing a week is permanent. That is why `fetch` runs DAILY even though the data is
weekly: we would have to miss five consecutive sessions to actually lose a snapshot.
Re-running on an already-stored date is a no-op (INSERT OR REPLACE on the same key).

DATA SHAPE (verified 2026-09-14)
--------------------------------
CSV: 資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%   -- UTF-8 BOM, CRLF.
4,055 codes x 17 levels = 68,935 rows per snapshot.
**證券代號 is space-padded to 6 chars** (`'2330  '`) -- strip it or every join
against `price.code` silently returns nothing.

持股分級 (shares, not 張):
   1: 1-999 (零股)      2: 1,000-5,000       3: 5,001-10,000
   4: 10,001-15,000     5: 15,001-20,000     6: 20,001-30,000
   7: 30,001-40,000     8: 40,001-50,000     9: 50,001-100,000
  10: 100,001-200,000  11: 200,001-400,000  12: 400,001-600,000
  13: 600,001-800,000  14: 800,001-1,000,000  15: 1,000,001+
  16: 差異數調整        17: 合計

NOT A SCORED FACTOR. One snapshot exists today; a weight needs a full-window plus
sub-period measurement, which is ~2 years away. See HANDOFF/03_DECISION_LOG.md D7.
Everything here is display-only, exactly like `news_signal`.
"""
import sqlite3, argparse, os, sys, datetime as dt

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tdcc.db")
URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
PC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), ".claude", "skills", "pc-operation", "pc.py")

BIG_LV = (12, 13, 14, 15)     # 400 張以上 = 大戶
MEGA_LV = (15,)               # 1,000 張以上 = 千張大戶
RETAIL_LV = (1, 2, 3)         # 10 張以下 = 散戶
TOTAL_LV = 17


def conn(db=DB):
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE IF NOT EXISTS tdcc(
                   date TEXT, code TEXT, lv INTEGER,
                   people INTEGER, shares REAL, pct REAL,
                   PRIMARY KEY(date, code, lv))""")
    c.execute("CREATE INDEX IF NOT EXISTS i_t_code ON tdcc(code)")
    c.execute("CREATE INDEX IF NOT EXISTS i_t_date ON tdcc(date)")
    return c


def parse(path):
    """CSV -> rows. Drops all-zero levels (~25% of the file) to keep the archive
    lean; a level absent for a date that HAS a 合計 row means zero, not missing.
    The 合計 (17) row is always kept, so presence-of-date is never ambiguous."""
    rows, bad = [], 0
    with open(path, encoding="utf-8-sig") as f:
        next(f, None)
        for ln in f:
            p = ln.rstrip("\r\n").split(",")
            if len(p) < 6:
                bad += 1
                continue
            try:
                d, code, lv = p[0].strip(), p[1].strip(), int(p[2])
                ppl, sh, pct = int(p[3]), float(p[4]), float(p[5])
            except ValueError:
                bad += 1
                continue
            if len(d) != 8 or not d.isdigit() or not code:
                bad += 1
                continue
            if lv != TOTAL_LV and ppl == 0 and sh == 0:
                continue
            rows.append((f"{d[:4]}-{d[4:6]}-{d[6:]}", code, lv, ppl, sh, pct))
    return rows, bad


def store(rows, db=DB):
    c = conn(db)
    before = c.execute("SELECT count(DISTINCT date) FROM tdcc").fetchone()[0]
    c.executemany("INSERT OR REPLACE INTO tdcc VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    after = c.execute("SELECT count(DISTINCT date) FROM tdcc").fetchone()[0]
    rng = c.execute("SELECT min(date), max(date), count(*) FROM tdcc").fetchone()
    c.close()
    return dict(new_snapshot=(after > before), snapshots=after,
                span=rng[:2], total_rows=rng[2])


def fetch(db=DB):
    """Pull the snapshot via the PC bridge (this host has no external egress)."""
    import subprocess, tempfile
    remote = r"C:\myclaw_tw\tdcc.csv"
    code = ("import urllib.request,os\n"
            "os.makedirs(r'C:\\myclaw_tw',exist_ok=True)\n"
            f"b=urllib.request.urlopen('{URL}',timeout=90).read()\n"
            f"open(r'{remote}','wb').write(b)\n"
            "print('bytes',len(b))\n")
    r = subprocess.run([sys.executable, PC, "exec", code],
                       capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        raise RuntimeError("PC fetch failed: " + (r.stderr or r.stdout)[-400:])
    tmp = os.path.join(tempfile.gettempdir(), "tdcc_dl.csv")
    r = subprocess.run([sys.executable, PC, "download", remote, tmp],
                       capture_output=True, text=True, timeout=240)
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError("PC download failed: " + (r.stderr or r.stdout)[-400:])
    rows, bad = parse(tmp)
    if len(rows) < 30000:
        raise RuntimeError(f"short file: only {len(rows)} usable rows -- refusing to store")
    info = store(rows, db)
    info.update(parsed=len(rows), malformed=bad)
    return info


# ------------------------------------------------------------------ metrics
def _pct(c, date, code, lvs):
    q = ",".join("?" * len(lvs))
    v = c.execute(f"SELECT sum(pct) FROM tdcc WHERE date=? AND code=? AND lv IN ({q})",
                  (date, code, *lvs)).fetchone()[0]
    return v


def concentration(codes, db=DB, n_back=2):
    """Display-only 籌碼集中度 for `codes`: 大戶(400張+) / 千張大戶 / 散戶(10張以下)
    share of 集保庫存, plus the change vs the previous snapshot.

    Returns {} until two snapshots exist -- the delta is the whole point, and a
    single-snapshot level on its own invites reading noise as a trend.
    """
    if not os.path.exists(db):
        return {}
    c = conn(db)
    ds = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM tdcc ORDER BY date DESC LIMIT ?", (n_back,))]
    if not ds:
        c.close()
        return {}
    cur = ds[0]
    prev = ds[1] if len(ds) > 1 else None
    out = {}
    for code in codes:
        code = str(code).strip()
        big = _pct(c, cur, code, BIG_LV)
        if big is None:
            continue
        mega = _pct(c, cur, code, MEGA_LV) or 0.0
        ret = _pct(c, cur, code, RETAIL_LV) or 0.0
        tot = c.execute("SELECT people FROM tdcc WHERE date=? AND code=? AND lv=?",
                        (cur, code, TOTAL_LV)).fetchone()
        row = dict(asof=cur, big=round(big, 2), mega=round(mega, 2),
                   retail=round(ret, 2), holders=(tot[0] if tot else None))
        if prev:
            pb = _pct(c, prev, code, BIG_LV)
            pm = _pct(c, prev, code, MEGA_LV)
            ph = c.execute("SELECT people FROM tdcc WHERE date=? AND code=? AND lv=?",
                           (prev, code, TOTAL_LV)).fetchone()
            row["prev"] = prev
            row["d_big"] = round(big - pb, 2) if pb is not None else None
            row["d_mega"] = round(mega - pm, 2) if pm is not None else None
            row["d_holders"] = (row["holders"] - ph[0]
                                if (ph and row["holders"] is not None) else None)
        out[code] = row
    c.close()
    return out


def status(db=DB):
    if not os.path.exists(db):
        return dict(snapshots=0, span=(None, None), total_rows=0, stale_days=None)
    c = conn(db)
    n = c.execute("SELECT count(DISTINCT date) FROM tdcc").fetchone()[0]
    lo, hi, rows = c.execute("SELECT min(date), max(date), count(*) FROM tdcc").fetchone()
    c.close()
    stale = ((dt.date.today() - dt.date.fromisoformat(hi)).days if hi else None)
    return dict(snapshots=n, span=(lo, hi), total_rows=rows, stale_days=stale)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["fetch", "status", "show"])
    ap.add_argument("--db", default=DB)
    ap.add_argument("--codes", default="2330,2317,2454")
    a = ap.parse_args()

    if a.cmd == "fetch":
        info = fetch(a.db)
        print("tdcc fetch:", info)
        if not info["new_snapshot"]:
            print("  (same snapshot as last run -- nothing new published yet)")
    elif a.cmd == "status":
        print("tdcc status:", status(a.db))
    else:
        st = status(a.db)
        print("tdcc status:", st)
        for k, v in concentration(a.codes.split(","), a.db).items():
            print(" ", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
