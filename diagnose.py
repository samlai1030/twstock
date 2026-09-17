#!/usr/bin/env python3
"""Attribution: where does the strategy's shortfall vs 0050 actually come from?

These are DIAGNOSTICS, not candidate strategies. Each one switches off exactly
one mechanism so we can price it. Picking whichever variant scores best on this
same year and calling it 'the strategy' would be textbook overfitting -- the
whole point is to explain the baseline, not to beat the benchmark in-sample.
"""
import json, copy, sys
import strategy as S
from report import metrics, benchmark, trade_stats

DB, START, END = "twstock.db", "2025-08-14", "2026-08-14"
BASE = copy.deepcopy(S.P)

VARIANTS = [
    ("baseline (as specified)",      {}),
    ("no trading costs",             dict(fee_rate=0.0, tax_rate=0.0, tax_rate_etf=0.0,
                                          slippage=0.0, min_fee=0.0)),
    ("no stops / no emergency",      dict(stop_loss=-9.9, trail_stop=-9.9,
                                          crash_day=-9.9, crash_dd=-9.9)),
    ("no emergency (keep stops)",    dict(crash_day=-9.9, crash_dd=-9.9)),
    ("hold 20 names not 8",          dict(top_n=20)),
    ("monthly-ish: 25 names",        dict(top_n=25)),
]

rows = []
for name, over in VARIANTS:
    for k in BASE:
        S.P[k] = BASE[k]
    S.P.update(over)
    res = S.backtest(DB, START, END)
    m = metrics(res["equity"], name, base=BASE["capital"])
    ts = trade_stats(res["trades"], res["px"])
    cost = sum(t["cost"] for t in res["trades"])
    nemg = sum(1 for e in res["events"] if e["kind"] == "EMERGENCY_EXIT")
    rows.append(dict(name=name, ret=m["total_return"], cagr=m["cagr"], sharpe=m["sharpe"],
                     mdd=m["mdd"], vol=m["vol"], n=ts["n"], wr=ts["win_rate"],
                     pf=ts["profit_factor"], cost=cost, emg=nemg))
    print("%-28s ret %+7.1f%%  sharpe %5.2f  mdd %6.1f%%  trades %4d  cost NT$%7.0f  emg %2d"
          % (name, m["total_return"] * 100, m["sharpe"], m["mdd"] * 100, ts["n"], cost, nemg))

for k in BASE:
    S.P[k] = BASE[k]
res = S.backtest(DB, START, END)
b = benchmark(res["px"], res["dates"],
              next(i for i, d in enumerate(res["dates"]) if d >= START),
              max(i for i, d in enumerate(res["dates"]) if d <= END), BASE["market_proxy"])
mb = metrics(b, "0050 buy&hold", base=BASE["capital"])
print("%-28s ret %+7.1f%%  sharpe %5.2f  mdd %6.1f%%"
      % ("0050 buy & hold", mb["total_return"] * 100, mb["sharpe"], mb["mdd"] * 100))
rows.append(dict(name="0050 buy & hold", ret=mb["total_return"], cagr=mb["cagr"],
                 sharpe=mb["sharpe"], mdd=mb["mdd"], vol=mb["vol"], n=1, wr=None,
                 pf=None, cost=0, emg=0))
json.dump(rows, open("diagnostics.json", "w"), ensure_ascii=False)
print("\nwrote diagnostics.json")
