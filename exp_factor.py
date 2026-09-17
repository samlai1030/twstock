#!/usr/bin/env python3
"""EXPERIMENT (throwaway): does the 自營商 (dealer) leg of 三大法人 earn a weight?

Sweeps W["dlr"] over the full window AND both half-year sub-periods. The
sub-period split is not optional -- 03_DECISION_LOG.md D2 records a change that
showed a broad +38pp plateau on the full window and turned out to be one
time-concentrated stretch. A weight is only interesting if BOTH halves agree.

Run:  python3 exp_dealer.py            # weight sweep
      python3 exp_dealer.py --win      # dealer-window sweep at the best weight
"""
import argparse, math, json
import strategy as S
import report as R

DB = "twstock.db"
FULL = ("2025-09-15", "2026-09-14")
H1 = ("2025-09-15", "2026-03-13")
H2 = ("2026-03-16", "2026-09-14")


def run(ctx, start, end):
    res = S.backtest_ctx(ctx, start, end)
    m = R.metrics(res["equity"], "s", base=S.P["capital"])
    ts = R.trade_stats(res["trades"], res["px"])
    return dict(ret=m["total_return"], sharpe=m["sharpe"], mdd=m["mdd"],
                vol=m["vol"], n=ts["n"], win=ts["win_rate"], pf=ts["profit_factor"])


def show(tag, r):
    print(f"  {tag:<12} ret {r['ret']:+7.1%}  Sharpe {r['sharpe']:+5.2f}  "
          f"MDD {r['mdd']:+6.1%}  vol {r['vol']:5.1%}  "
          f"trades {r['n']:3d}  win {r['win']:5.1%}  PF {r['pf']:4.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="dlr", help="W key to sweep (dlr | fgnp)")
    ap.add_argument("--weights", default="0,0.10,0.15,0.20,0.25,-0.10,-0.15")
    ap.add_argument("--out", default="exp_dealer.json")
    a = ap.parse_args()

    print("loading DB once ...")
    ctx = S.make_ctx(DB, "news.json.gz")
    out = {}

    grid = [("%s=%+.2f" % (a.key, float(w)), float(w)) for w in a.weights.split(",")]

    for tag, val in grid:
        S.W[a.key] = val
        print(f"\n{tag}")
        row = {}
        for name, (s, e) in (("FULL", FULL), ("H1", H1), ("H2", H2)):
            row[name] = run(ctx, s, e)
            show(name, row[name])
        out[tag] = row

    S.W[a.key] = 0.0
    json.dump(out, open(a.out, "w"), indent=1)
    print("\nwrote", a.out)


if __name__ == "__main__":
    main()
