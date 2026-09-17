#!/usr/bin/env python3
"""Backtest the (a) risk-adjusted-momentum and (b) volatility-ceiling guards
against the baseline on the full window. One DB load, four param combos.
Reports return/Sharpe/vol/MDD/trades and whether 7610 (the loss that prompted
this) ever gets bought under each. NOT fitted -- thresholds are hand-set."""
import strategy as S
from report import metrics
import copy

START, END = "2025-08-18", "2026-08-14"
VOL_CEIL = 0.06   # hand-set: drops the top-vol tail (7610 was 0.079); NOT tuned to sample

BASE = copy.deepcopy(S.P)
ctx = S.make_ctx("twstock.db")

def run(label, over):
    S.P.clear(); S.P.update(copy.deepcopy(BASE)); S.P.update(over)
    res = S.backtest_ctx(ctx, START, END)
    m = metrics(res["equity"], label)
    buys = [t for t in res["trades"] if t["side"] == "BUY"]
    n7610 = sum(1 for t in buys if t["code"] == "7610")
    # names ever held (distinct BUY codes)
    names = len({t["code"] for t in buys})
    return m, len(res["trades"]), n7610, names

combos = [
    ("baseline",            dict()),
    ("(a) mom_risk_adj",    dict(mom_risk_adj=True)),
    ("(b) vol_ceiling .06", dict(vol_ceiling=VOL_CEIL)),
    ("(a)+(b)",             dict(mom_risk_adj=True, vol_ceiling=VOL_CEIL)),
]

print(f"window {START} .. {END}\n")
hdr = f"{'variant':22} {'return':>8} {'CAGR':>7} {'Sharpe':>7} {'vol':>6} {'MDD':>7} {'trades':>7} {'7610buys':>8} {'names':>6}"
print(hdr); print("-"*len(hdr))
for label, over in combos:
    m, ntr, n7610, names = run(label, over)
    print(f"{label:22} {m['total_return']*100:7.1f}% {m['cagr']*100:6.1f}% "
          f"{m['sharpe']:7.2f} {m['vol']*100:5.1f}% {m['mdd']*100:6.1f}% "
          f"{ntr:7d} {n7610:8d} {names:6d}")

# restore
S.P.clear(); S.P.update(BASE)
