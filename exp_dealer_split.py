#!/usr/bin/env python3
"""EXPERIMENT: does the 自營商 (dealer) split earn a weight?

Decision log D5 tested the AGGREGATE dealer_net and found pure noise in both
directions on all three windows. The mechanism left open: the aggregate mixes
自行買賣 (proprietary desks' directional view) with 避險 (hedging against
warrants they issued -- non-directional by construction), so the hedge leg may
dilute any directional signal. This tests the split legs separately.

Methodology (per rules A1/A2): hand-set construction (10d turnover-normalised
z-score, same as the D5 dealer test), reported on FULL window AND both
half-year sub-periods. A leg is only interesting if BOTH halves agree with the
full window. The 避險 leg is the negative control -- the mechanism predicts ~0.

Also reports data coverage: the split columns only exist in the 19-col T86
layout, so pre-split-era rows carry NULL. If coverage in the window is thin,
the result means nothing and the script says so.

Run:  python3 exp_dealer_split.py [--out exp_dealer_split.json]
"""
import argparse, json
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


def coverage(ctx):
    """Fraction of chip rows in the window carrying the split; first covered date."""
    import sqlite3
    con = sqlite3.connect(DB)
    tot = con.execute(
        "SELECT COUNT(*) FROM chip WHERE date BETWEEN ? AND ?", FULL).fetchone()[0]
    cov = con.execute(
        "SELECT COUNT(*) FROM chip WHERE date BETWEEN ? AND ? "
        "AND dealer_self IS NOT NULL", FULL).fetchone()[0]
    first = con.execute(
        "SELECT MIN(date) FROM chip WHERE dealer_self IS NOT NULL").fetchone()[0]
    # arithmetic sanity: dealer_net should equal self + hedge where split exists
    bad = con.execute(
        "SELECT COUNT(*) FROM chip WHERE dealer_self IS NOT NULL "
        "AND ABS(dealer_net - (dealer_self + dealer_hedge)) > 1.0").fetchone()[0]
    con.close()
    return tot, cov, first, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="exp_dealer_split.json")
    a = ap.parse_args()

    print("loading DB once ...")
    ctx = S.make_ctx(DB)

    tot, cov, first, bad = coverage(ctx)
    print(f"\nchip rows in window: {tot}, with split: {cov} "
          f"({cov / max(1, tot):.1%}), first split date: {first}")
    print(f"arithmetic violations (dealer_net != self+hedge): {bad}")
    if cov < 0.8 * tot:
        print("COVERAGE WARNING: split missing on >20% of window rows -- "
              "treat the sweep as provisional.")

    out = {"coverage": dict(rows=tot, split_rows=cov, first_split_date=first,
                            arithmetic_violations=bad)}

    grid = [("baseline", "dlr_self", 0.0)]
    for w in (0.10, 0.15, 0.20, 0.25, -0.10, -0.15):
        grid.append((f"dlr_self={w:+.2f}", "dlr_self", w))
    # negative control: the mechanism predicts the hedge leg is noise
    grid.append(("dlr_hedge=+0.15 (neg ctrl)", "dlr_hedge", 0.15))
    grid.append(("dlr_hedge=-0.15 (neg ctrl)", "dlr_hedge", -0.15))

    for tag, key, val in grid:
        S.W["dlr_self"] = 0.0
        S.W["dlr_hedge"] = 0.0
        S.W[key] = val
        print(f"\n{tag}")
        row = {}
        for name, (s, e) in (("FULL", FULL), ("H1", H1), ("H2", H2)):
            row[name] = run(ctx, s, e)
            show(name, row[name])
        out[tag] = row

    S.W["dlr_self"] = 0.0
    S.W["dlr_hedge"] = 0.0
    json.dump(out, open(a.out, "w"), indent=1, ensure_ascii=False)
    print("\nwrote", a.out)


if __name__ == "__main__":
    main()
