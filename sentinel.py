#!/usr/bin/env python3
"""Look-ahead sentinel — the honest backtest must stay FAR below a known-cheating one.

Rationale: leakage cannot be spotted by staring at a return number, because a
leaky backtest just looks good. What it cannot do is stay far away from a
deliberate cheat. So we build the cheat (rank by TOMORROW's realised return) and
require a wide margin. If the honest run ever creeps toward it, something started
reading the future.

Cost control: this runs two full backtests, so it fires only when it can actually
tell us something -- when strategy.py changed, or once a week as a regression.
Pass --force to run it anyway.

Exit 0 = clean, 1 = suspicious (caller should alert and NOT trust the numbers).
"""
import argparse, copy, hashlib, json, os, sys, datetime as dt
import strategy as S
from report import metrics, trade_stats

DB, START, END = "twstock.db", "2025-08-14", "2026-08-14"
HASHFILE = ".sentinel_hash"
RATIO_MAX = 0.50        # honest may not reach 50% of the cheat's return or Sharpe


def run(signal_mod=None):
    ctx = S.make_ctx(DB)
    dates = ctx["dates"]
    orig = S.build_signals
    if signal_mod:
        S.build_signals = signal_mod(ctx, orig)
    try:
        di0 = next(i for i, d in enumerate(dates) if d >= START)
        di1 = max(i for i, d in enumerate(dates) if d <= END)
        e = S.Engine(ctx, S.P["capital"])
        for di in range(di0, di1 + 1):
            e.step(di, last=(di == di1))
        return metrics(e.equity, "x", base=S.P["capital"])
    finally:
        S.build_signals = orig


def future_rank(shift=1):
    def maker(ctx, orig):
        dates = ctx["dates"]
        def f(P_, chip, mgn, ds, di, uni, news=None):
            sc, vol, raw = orig(P_, chip, mgn, ds, di, uni, news)
            j = min(di + shift, len(dates) - 1)
            fut = {}
            for c in sc:
                a, b = P_.get(c, ds[di]), P_.get(c, ds[j])
                if a and b and a > 0:
                    fut[c] = b / a - 1.0
            return (fut or sc), vol, raw
        return f
    return maker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--weekly-day", type=int, default=4)   # Friday
    a = ap.parse_args()

    src = hashlib.sha256(open("strategy.py", "rb").read()).hexdigest()[:16]
    prev = open(HASHFILE).read().strip() if os.path.exists(HASHFILE) else ""
    changed = (src != prev)
    is_weekly = dt.date.today().weekday() == a.weekly_day
    if not (a.force or changed or is_weekly):
        print("sentinel: skipped (strategy.py unchanged, not the weekly slot)")
        return 0

    why = "strategy.py changed" if changed else ("weekly regression" if is_weekly else "forced")
    print("sentinel: running (%s)" % why)

    honest = run()
    cheat = run(signal_mod=future_rank(1))
    r_ret = honest["total_return"] / cheat["total_return"] if cheat["total_return"] > 0 else 0.0
    r_shp = honest["sharpe"] / cheat["sharpe"] if cheat["sharpe"] > 0 else 0.0

    print("  honest : ret %+.1f%%  sharpe %.2f" % (honest["total_return"] * 100, honest["sharpe"]))
    print("  cheat  : ret %+.1f%%  sharpe %.2f" % (cheat["total_return"] * 100, cheat["sharpe"]))
    print("  ratio  : return %.1f%%  sharpe %.1f%%  (alert above %.0f%%)"
          % (r_ret * 100, r_shp * 100, RATIO_MAX * 100))

    json.dump(dict(when=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), src=src, why=why,
                   honest=honest, cheat=cheat, ratio_ret=r_ret, ratio_sharpe=r_shp),
              open("sentinel_last.json", "w"), ensure_ascii=False)

    if cheat["total_return"] <= honest["total_return"]:
        print("SUSPICIOUS: the cheating variant did NOT beat the honest one -- either the "
              "cheat is broken or the honest run is already using future data.")
        return 1
    if r_ret > RATIO_MAX or r_shp > RATIO_MAX:
        print("SUSPICIOUS: honest run is too close to the cheat. Treat results as LEAKY.")
        return 1

    open(HASHFILE, "w").write(src)
    print("sentinel: CLEAN")
    return 0


sys.exit(main())
