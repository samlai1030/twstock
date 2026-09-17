#!/usr/bin/env python3
"""v0 parameter optimization (Sam 2026-08-17: "用過去兩年歷史數據做 v0 最佳化").

HONEST METHODOLOGY -- the whole point of a v0 is that "optimized" must not mean
"curve-fit to noise":

* The 2 years of raw data (2024-08..2026-08) mostly go to MA200 warm-up; clean
  backtesting only starts 2025-06-03. Usable window ~14 months.
* Split it: search on the IN-SAMPLE half, then report the winner on an
  OUT-OF-SAMPLE half that the search never sees. OOS is the only unbiased estimate
  of what optimization actually bought.
* Selection rule is PRE-COMMITTED: best in-sample Sharpe with >= MIN_TRADES
  activity (a 3-trade fluke can post a huge Sharpe). We do NOT pick by OOS -- that
  would just move the overfitting one level up. The top-K OOS spread is printed
  only to SHOW how much of the ranking is luck.
* News weight is NOT optimized: there is no news history to fit, so it stays at
  its pre-set value.

Run: python3 optimize.py [N]      (N = random samples, default 250)
"""
import sys, json, random
import multiprocessing as mp
import strategy as S
from report import metrics

IS = ("2025-06-03", "2026-01-30")     # in-sample: search here
OOS = ("2026-02-02", "2026-08-14")    # out-of-sample: report here, never searched
MIN_TRADES = 20

SPACE_P = {
    "top_n":          [4, 5, 6],
    "lookback_mom":   [40, 60, 90, 120],
    "mom_skip":       [3, 5, 10],
    "chip_fgn_win":   [10, 20, 40],
    "chip_tru_win":   [5, 10, 20],
    "margin_win":     [10, 20, 40],
    "vol_win":        [10, 20, 40],
    "stop_loss":      [-0.06, -0.08, -0.10, -0.12],
    "trail_stop":     [-0.10, -0.12, -0.15, -0.20],
    "conv_tau":       [0.4, 0.6, 0.9, 1.2],
    "conv_max_weight": [0.20, 0.25, 0.30],
    "conv_min_weight": [0.05, 0.08, 0.10],
}
SPACE_W = {
    "mom":    [0.25, 0.35, 0.45],
    "fgn":    [0.20, 0.30, 0.40],
    "tru":    [0.15, 0.25, 0.35],
    "margin": [-0.05, -0.10, -0.15],
}

_ctx = None


def _init():
    global _ctx
    _ctx = S.make_ctx("twstock.db")


def _run(pp, ww, window):
    S.P.update(pp)
    S.W.update(ww)
    r = S.backtest_ctx(_ctx, *window)
    eq = r["equity"]
    if len(eq) < 3:
        return None, 0
    return metrics(eq, "", base=1e6), len(r["trades"])


def _eval(args):
    idx, pp, ww = args
    try:
        m, nt = _run(pp, ww, IS)
    except Exception:
        return None
    if not m:
        return None
    return dict(idx=idx, P=pp, W=ww, is_sharpe=m["sharpe"], is_ret=m["total_return"],
                is_mdd=m["mdd"], is_calmar=m.get("calmar", 0.0), trades=nt)


def _sample(rng):
    pp = {k: rng.choice(v) for k, v in SPACE_P.items()}
    # feasibility: floor must fit top_n and sit below the cap
    pp["conv_min_weight"] = min(pp["conv_min_weight"], 0.9 / pp["top_n"])
    if pp["conv_min_weight"] >= pp["conv_max_weight"]:
        pp["conv_max_weight"] = round(pp["conv_min_weight"] + 0.10, 3)
    ww = {k: rng.choice(v) for k, v in SPACE_W.items()}
    return pp, ww


def main(N=250):
    P0, W0 = dict(S.P), dict(S.W)                       # hand-set baseline
    rng = random.Random(42)
    combos = [(i, *_sample(rng)) for i in range(N)]
    with mp.Pool(min(8, mp.cpu_count()), initializer=_init) as pool:
        res = [r for r in pool.map(_eval, combos) if r]
    res = [r for r in res if r["trades"] >= MIN_TRADES]
    res.sort(key=lambda x: -x["is_sharpe"])
    print("evaluated %d/%d combos with >=%d trades" % (len(res), N, MIN_TRADES))

    _init()                                            # ctx for the reporting pass

    def report(pp, ww):
        S.P.clear(); S.P.update(P0); S.P.update(pp)
        S.W.clear(); S.W.update(W0); S.W.update(ww)
        mi, ti = _run(pp, ww, IS)
        mo, to = _run(pp, ww, OOS)
        return mi, ti, mo, to

    print("\n=== BASELINE (hand-set, current) ===")
    bmi, bti, bmo, bto = report({}, {})
    print("  IS : ret %+6.1f%%  sharpe %5.2f  mdd %5.1f%%  trades %d"
          % (bmi["total_return"]*100, bmi["sharpe"], bmi["mdd"]*100, bti))
    print("  OOS: ret %+6.1f%%  sharpe %5.2f  mdd %5.1f%%  trades %d"
          % (bmo["total_return"]*100, bmo["sharpe"], bmo["mdd"]*100, bto))

    print("\n=== TOP 8 by IN-SAMPLE Sharpe (OOS shown for transparency, NOT used to pick) ===")
    print("  rank | IS sharpe  IS ret | OOS sharpe  OOS ret  OOS mdd  trades")
    top = res[:8]
    oos_cache = []
    for k, r in enumerate(top):
        mi, ti, mo, to = report(r["P"], r["W"])
        oos_cache.append((mo, to))
        print("  %4d | %8.2f  %+5.1f%% | %9.2f  %+6.1f%%  %5.1f%%  %d"
              % (k+1, r["is_sharpe"], r["is_ret"]*100, mo["sharpe"],
                 mo["total_return"]*100, mo["mdd"]*100, to))

    best = top[0]                                       # PRE-COMMITTED: best IS Sharpe
    bmo2, bto2 = oos_cache[0]
    out = dict(method="random-search v0", n=N, is_window=IS, oos_window=OOS,
               selection="best in-sample Sharpe, trades>=%d" % MIN_TRADES,
               baseline=dict(is_sharpe=bmi["sharpe"], is_ret=bmi["total_return"],
                             oos_sharpe=bmo["sharpe"], oos_ret=bmo["total_return"],
                             oos_mdd=bmo["mdd"]),
               chosen=dict(P=best["P"], W=best["W"],
                           is_sharpe=best["is_sharpe"], is_ret=best["is_ret"],
                           oos_sharpe=bmo2["sharpe"], oos_ret=bmo2["total_return"],
                           oos_mdd=bmo2["mdd"], oos_trades=bto2))
    json.dump(out, open("optimized_params.json", "w"), ensure_ascii=False, indent=1)
    print("\nCHOSEN (best IS Sharpe): P=%s\n  W=%s" % (best["P"], best["W"]))
    print("wrote optimized_params.json")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 250)
