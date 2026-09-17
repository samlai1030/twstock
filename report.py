#!/usr/bin/env python3
"""Run the backtest, compute risk-adjusted metrics, emit a self-contained dashboard."""
import json, math, sqlite3, argparse, datetime as dt, os, gzip, html
import strategy as S

RF = 0.015          # TWD risk-free, annual
TD = 252


def metrics(curve, label, base=None):
    eq = [c["equity"] for c in curve]
    if len(eq) < 3:
        return {}
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq)) if eq[i - 1] > 0]
    n = len(eq)
    yrs = n / TD
    # measure from the capital actually committed: both the strategy and the
    # benchmark start the window holding NT$1M, so that is the common base.
    # Using the benchmark's own day-1 close would quietly hide its first-day move.
    base = base or eq[0]
    tot = eq[-1] / base - 1.0
    cagr = (eq[-1] / base) ** (1 / yrs) - 1.0 if yrs > 0 and base > 0 else 0.0
    mu = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) if len(rets) > 1 else 0.0
    vol = sd * math.sqrt(TD)
    sharpe = (cagr - RF) / vol if vol > 1e-9 else 0.0
    dn = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in dn) / len(dn)) * math.sqrt(TD) if dn else 0.0
    sortino = (cagr - RF) / dsd if dsd > 1e-9 else 0.0
    peak, mdd, mdd_at = eq[0], 0.0, curve[0]["date"]
    for c in curve:
        peak = max(peak, c["equity"])
        d = c["equity"] / peak - 1.0
        if d < mdd:
            mdd, mdd_at = d, c["date"]
    return dict(label=label, start=curve[0]["date"], end=curve[-1]["date"], days=n,
                start_eq=round(eq[0]), end_eq=round(eq[-1]), total_return=tot,
                cagr=cagr, vol=vol, sharpe=sharpe, sortino=sortino,
                mdd=mdd, mdd_at=mdd_at, calmar=(cagr / abs(mdd) if mdd < -1e-9 else 0.0),
                best_day=max(rets) if rets else 0, worst_day=min(rets) if rets else 0,
                pos_days=sum(1 for r in rets if r > 0) / len(rets) if rets else 0)


def benchmark(px, dates, di0, di1, code="0050"):
    """Buy-and-hold the market proxy with identical costs -- the honest comparison."""
    o = px.get(code, dates[di0], "o") or px.get(code, dates[di0])
    if not o:
        return []
    p_eff = o * (1 + S.P["slippage"])
    sh = math.floor(S.P["capital"] / (p_eff * (1 + S.P["fee_rate"])))
    cash = S.P["capital"] - sh * p_eff - max(S.P["min_fee"], sh * p_eff * S.P["fee_rate"])
    out = []
    for di in range(di0, di1 + 1):
        c = px.get(code, dates[di]) or o
        out.append(dict(date=dates[di], equity=round(cash + sh * c), cash=round(cash), npos=1, dd=0))
    return out


def trade_stats(trades, px):
    """Round-trip P&L by pairing BUYs with the SELL that closes them (FIFO)."""
    lots, closed = {}, []
    for t in trades:
        c = t["code"]
        if t["side"] == "BUY":
            # copy: the FIFO match below decrements the open quantity, and
            # mutating the caller's trade records would zero out the shipped log
            lots.setdefault(c, []).append(dict(t))
        else:
            q = t["sh"]
            while q > 0 and lots.get(c):
                b = lots[c][0]
                take = min(q, b["sh"])
                pnl = take * (t["price"] - b["price"]) - (t["cost"] * take / max(t["sh"], 1)) \
                      - (b["cost"] * take / max(b["sh"], 1))
                closed.append(dict(code=c, buy=b["date"], sell=t["date"], sh=take,
                                   ret=(t["price"] / b["price"] - 1.0), pnl=pnl, why=t["why"]))
                b["sh"] -= take; q -= take
                if b["sh"] <= 0:
                    lots[c].pop(0)
    wins = [c for c in closed if c["pnl"] > 0]
    loss = [c for c in closed if c["pnl"] <= 0]
    gp = sum(c["pnl"] for c in wins); gl = -sum(c["pnl"] for c in loss)
    return dict(n=len(closed), win=len(wins), lose=len(loss),
                win_rate=len(wins) / len(closed) if closed else 0,
                avg_win=(gp / len(wins)) if wins else 0,
                avg_loss=(-gl / len(loss)) if loss else 0,
                profit_factor=(gp / gl) if gl > 1e-9 else 0,
                best=max(closed, key=lambda c: c["pnl"]) if closed else None,
                worst=min(closed, key=lambda c: c["pnl"]) if closed else None,
                closed=closed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="twstock.db")
    ap.add_argument("--start", default="2025-08-18")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--news", default="news.json.gz")
    ap.add_argument("--holdings", default="holdings.json")
    ap.add_argument("--out", default="tw_dashboard.html")
    ap.add_argument("--json-out", default="result.json")
    a = ap.parse_args()

    res = S.backtest(a.db, a.start, a.end)
    px, dates = res["px"], res["dates"]
    di0 = next(i for i, d in enumerate(dates) if d >= a.start)
    di1 = max(i for i, d in enumerate(dates) if d <= a.end)

    bench = benchmark(px, dates, di0, di1, S.P["market_proxy"])
    m_str = metrics(res["equity"], "Strategy", base=S.P["capital"])
    m_bmk = metrics(bench, "0050 buy & hold", base=S.P["capital"]) if bench else {}
    ts = trade_stats(res["trades"], px)
    total_cost = sum(t["cost"] for t in res["trades"])

    # ---- current signal set (latest session) --------------------------------
    latest = res["weekly"][-1] if res["weekly"] else None

    # ---- holdings review (requirement 2) ------------------------------------
    holdings = None
    if os.path.exists(a.holdings):
        raw_h = json.load(open(a.holdings, encoding="utf-8"))
        holdings = S.review_holdings(res, raw_h, asof=dates[di1])
        # PixelCloud has no access control, so a page carrying real positions
        # must never be published there unlabelled. Mark whether this is the
        # shipped sample or someone's actual book.
        ex_f = "holdings.example.json"
        holdings["is_example"] = (os.path.exists(ex_f) and
                                  json.load(open(ex_f, encoding="utf-8")) == raw_h)

    news = []
    if os.path.exists(a.news):
        news = json.load(gzip.open(a.news, "rt", encoding="utf-8"))[:40]

    out = dict(meta=dict(generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                         start=a.start, end=a.end, capital=S.P["capital"],
                         params=S.P, weights=S.W),
               metrics=m_str, bench_metrics=m_bmk, trade_stats={k: v for k, v in ts.items() if k != "closed"},
               closed=ts["closed"][-200:], total_cost=total_cost,
               equity=res["equity"], bench=bench, weekly=res["weekly"],
               events=res["events"], trades=res["trades"][-300:],
               latest=latest, holdings=holdings, news=news,
               final_pos=[dict(code=c, sh=p["sh"], entry=round(p["entry"], 2),
                               last=round(p["last"], 2), ret=p["last"] / p["entry"] - 1.0)
                          for c, p in res["final_pos"].items()])
    json.dump(out, open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False)
    print("metrics :", json.dumps(m_str, ensure_ascii=False)[:400])
    print("bench   :", json.dumps(m_bmk, ensure_ascii=False)[:300])
    print("trades  :", ts["n"], "closed, win rate %.1f%%" % (ts["win_rate"] * 100),
          "PF %.2f" % ts["profit_factor"], "costs NT$%.0f" % total_cost)
    print("events  :", len(res["events"]), "| weekly decisions:", len(res["weekly"]))
    return out


if __name__ == "__main__":
    main()
