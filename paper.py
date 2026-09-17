#!/usr/bin/env python3
"""Forward paper trading — same Engine as the backtest, driven one session at a time.

  paper.py init  --capital 1000000        open an account, stage the first orders
  paper.py step                           advance through any new sessions in the DB
  paper.py orders                         print the order sheet for the next open
  paper.py report                         emit paper_result.json for the dashboard

State lives in paper_state.json and is keyed by DATE, so extending price history
backwards (for MA200 warm-up) never renumbers anything under it.

The loop mirrors reality: decisions are made on session D's close and FILLED at
session D+1's open. So `init` today stages orders that fill at tomorrow's open --
the same no-look-ahead rule the backtest is scored under.
"""
import json, os, math, argparse, datetime as dt
import strategy as S

STATE = "paper_state.json"


def load_state():
    return json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else None


def save_state(st):
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def engine_from(st, ctx):
    e = S.Engine(ctx, st["engine"]["capital"])
    e.restore(st["engine"])
    return e


def order_sheet(e, ctx, decided_date):
    """Indicative order sheet. Actual fills happen at the next open, which we do
    not know yet, so sizes are computed off the decision-day close and flagged
    as indicative -- never presented as the executed price."""
    pend = e.pending
    if not pend:
        return dict(decided=decided_date, fill_at="—", rows=[], note="no orders staged")
    P_, px = ctx["P_"], ctx["raw_px"]
    dates = ctx["dates"]
    di = dates.index(decided_date)
    if di + 1 < len(dates):
        nxt = dates[di + 1]
    else:                                   # tomorrow has not traded yet
        n = dt.date(*map(int, decided_date.split("-"))) + dt.timedelta(days=1)
        while n.weekday() >= 5:             # skip the weekend (holidays unknown here)
            n += dt.timedelta(days=1)
        nxt = n.isoformat() + " (next session)"
    tgt = pend.get("target") or []
    eq = e.cash + sum(p["sh"] * (P_.get(c, decided_date) or p["last"]) for c, p in e.pos.items())
    wts = pend.get("weights") or {}
    # per-name target NT$ from the stored conviction/risk weights (equity fractions)
    pers = {c: eq * wts.get(c, (pend["expo"] / len(tgt) if tgt else 0.0)) for c in tgt}
    rows = []
    for code in pend["sell"]:
        if code in e.pos:
            c = P_.get(code, decided_date) or e.pos[code]["last"]
            rows.append(dict(code=code, name=(px.get(code, {}).get(decided_date, {}) or {}).get("name", "").strip(),
                             side="SELL", shares=e.pos[code]["sh"], ref_price=round(c, 2),
                             amount=round(e.pos[code]["sh"] * c),
                             why=pend["why"].get(code, "rebalance")))
    # Drive each name to a lot-rule-conforming TARGET share count (mirror engine._fill):
    # holding >1000 -> whole 張, <=1000 -> odd. `heldsh` tracks the projected position.
    heldsh = {code: (e.pos[code]["sh"] if code in e.pos else 0) for code in tgt}
    for code in tgt:
        c = P_.get(code, decided_date)
        if not c:
            continue
        per = pers.get(code, 0.0)
        o_eff = c * (1 + S.P["slippage"]) * (1 + S.P["fee_rate"])
        have_sh = heldsh[code]
        want = S.snap_sh(per / o_eff)
        if abs((want - have_sh) * c) < per * 0.15:
            continue
        if want > have_sh:
            afford = math.floor(e.cash / o_eff)     # indicative: ignores prior buys' cash draw
            sh = S.snap_sh(have_sh + min(want - have_sh, afford)) - have_sh
            side = "BUY"
        else:
            sh = have_sh - want
            side = "SELL (trim)"
        if sh <= 0:
            continue
        heldsh[code] = have_sh + (sh if side == "BUY" else -sh)
        rows.append(dict(code=code, name=(px.get(code, {}).get(decided_date, {}) or {}).get("name", "").strip(),
                         side=side, shares=sh, ref_price=round(c, 2), amount=round(sh * c),
                         target_frac=round(wts.get(code, 0.0), 4),
                         why=pend["why"].get(code, "entry")))
    # Mirror the engine's top-up pass so the sheet shows what will actually be
    # ordered. Only whole-lot-regime names get a +1張 top-up (keeps totals conforming).
    lot = S.BOARD_LOT
    buys = {r["code"]: r for r in rows if r["side"] == "BUY"}
    cash_left = e.cash - sum(r["amount"] * (1 + S.P["slippage"]) * (1 + S.P["fee_rate"])
                             for r in buys.values())
    for _ in range(len(tgt) * 3):
        best, gap = None, 0.0
        for code in tgt:
            c = P_.get(code, decided_date)
            hs = heldsh.get(code, 0)
            if not c or hs < lot or hs % lot != 0:
                continue
            per = pers.get(code, 0.0)
            cost = lot * c * (1 + S.P["slippage"]) * (1 + S.P["fee_rate"])
            held = hs * c
            if cost <= cash_left and held + lot * c <= per * 1.02 and per - held > gap:
                best, gap = code, per - held
        if not best:
            break
        c = P_.get(best, decided_date)
        r = buys.get(best)
        if r:
            r["shares"] += lot
            r["amount"] = round(r["shares"] * c)
            if "(+top-up)" not in r["why"]:
                r["why"] += " (+top-up)"
        else:
            r = dict(code=best, name=(px.get(best, {}).get(decided_date, {}) or {}).get("name", "").strip(),
                     side="BUY", shares=lot, ref_price=round(c, 2), amount=round(lot * c),
                     target_frac=round(wts.get(best, 0.0), 4), why="top-up to target weight")
            rows.append(r); buys[best] = r
        heldsh[best] += lot
        cash_left -= lot * c * (1 + S.P["slippage"]) * (1 + S.P["fee_rate"])

    return dict(decided=decided_date, fill_at=nxt, rows=rows,
                weights={c: round(f, 4) for c, f in wts.items()},
                target_max=round(max(pers.values())) if pers else 0,
                target_min=round(min(pers.values())) if pers else 0,
                exposure=pend["expo"], equity=round(eq),
                lot_size=lot, sizing=S.P.get("size_mode", "equal"))


def cmd_init(a):
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    d = max(x for x in dates if x <= a.asof) if a.asof else dates[-1]
    di = dates.index(d)
    S.P["capital"] = a.capital
    e = S.Engine(ctx, a.capital)
    # force=True: opening an account mid-week should not wait for Friday
    e.rebalance(di, d, force=True)
    st = dict(engine=e.dump(), last_date=d, opened=d, capital=a.capital,
              created=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    save_state(st)
    sheet = order_sheet(e, ctx, d)
    json.dump(sheet, open("paper_orders.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("opened paper account: NT$%s, decision date %s, fills at %s open"
          % (f"{a.capital:,.0f}", d, sheet["fill_at"]))
    print("regime: %s | exposure %.0f%% | sizing %s | target/name NT$%s–%s"
          % (e.weekly[-1]["regime"] if e.weekly else "?", sheet.get("exposure", 0) * 100,
             sheet.get("sizing", "?"),
             f"{sheet.get('target_min',0):,.0f}", f"{sheet.get('target_max',0):,.0f}"))
    for r in sheet["rows"]:
        print("  %-11s %-6s %-10s %7d sh @ ~%8.2f  = NT$%9s   %s"
              % (r["side"], r["code"], r["name"][:10], r["shares"], r["ref_price"],
                 f"{r['amount']:,}", r["why"]))


def cmd_step(a):
    st = load_state()
    if not st:
        return print("no paper_state.json -- run `paper.py init` first")
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    S.P["capital"] = st["capital"]
    e = engine_from(st, ctx)
    new = [d for d in dates if d > st["last_date"]]
    if not new:
        return print("no new sessions since", st["last_date"])
    for d in new:
        e.step(dates.index(d), last=False)
        print("stepped", d, "equity NT$%s" % f"{e.equity[-1]['equity']:,}",
              "| pos", e.equity[-1]["npos"])
    st["engine"], st["last_date"] = e.dump(), new[-1]
    save_state(st)
    sheet = order_sheet(e, ctx, new[-1])
    json.dump(sheet, open("paper_orders.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("orders staged for %s: %d" % (sheet["fill_at"], len(sheet["rows"])))


def cmd_orders(a):
    s = json.load(open("paper_orders.json", encoding="utf-8"))
    print("decided %s -> fill at %s open" % (s["decided"], s["fill_at"]))
    for r in s["rows"]:
        print("  %-11s %-6s %-10s %7d sh @ ~%8.2f = NT$%9s  %s"
              % (r["side"], r["code"], r["name"][:10], r["shares"], r["ref_price"],
                 f"{r['amount']:,}", r["why"]))


def cmd_report(a):
    from report import metrics, benchmark, trade_stats
    st = load_state()
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    S.P["capital"] = st["capital"]
    e = engine_from(st, ctx)
    cur = e.equity or [dict(date=st["opened"], equity=st["capital"],
                            cash=st["capital"], npos=0, dd=0.0)]
    di0 = dates.index(cur[0]["date"])
    di1 = dates.index(cur[-1]["date"])
    bench = benchmark(ctx["P_"], dates, di0, di1, S.P["market_proxy"]) if di1 > di0 else []
    m = metrics(cur, "Paper", base=st["capital"]) if len(cur) >= 3 else {}
    mb = metrics(bench, "0050", base=st["capital"]) if len(bench) >= 3 else {}
    ts = trade_stats(e.trades, ctx["P_"])
    news = []
    if os.path.exists(a.news):
        import gzip
        news = json.load(gzip.open(a.news, "rt", encoding="utf-8"))[:40]
    orders = json.load(open("paper_orders.json", encoding="utf-8")) if os.path.exists("paper_orders.json") else None
    out = dict(meta=dict(generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                         start=st["opened"], end=cur[-1]["date"], capital=st["capital"],
                         params=S.P, weights=S.W, mode="paper"),
               metrics=m, bench_metrics=mb,
               trade_stats={k: v for k, v in ts.items() if k != "closed"},
               closed=ts["closed"][-200:], total_cost=sum(t["cost"] for t in e.trades),
               equity=cur, bench=bench, weekly=e.weekly, events=e.events,
               trades=e.trades[-300:], latest=(e.weekly[-1] if e.weekly else None),
               holdings=None, news=news, orders=orders,
               positions=[dict(code=c, name=(ctx["raw_px"].get(c, {}).get(cur[-1]["date"], {}) or {}).get("name", "").strip(),
                               sh=p["sh"], entry=round(p["entry"], 2), last=round(p["last"], 2),
                               value=round(p["sh"] * p["last"]),
                               ret=p["last"] / p["entry"] - 1.0) for c, p in e.pos.items()])
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print("wrote", a.out, "| sessions", len(cur), "| positions", len(e.pos),
          "| equity NT$%s" % f"{cur[-1]['equity']:,}")


ap = argparse.ArgumentParser()
ap.add_argument("--db", default="twstock.db")
sub = ap.add_subparsers(dest="cmd", required=True)
i = sub.add_parser("init"); i.add_argument("--capital", type=float, default=1_000_000.0)
i.add_argument("--asof", default=None); i.set_defaults(f=cmd_init)
s_ = sub.add_parser("step"); s_.set_defaults(f=cmd_step)
o = sub.add_parser("orders"); o.set_defaults(f=cmd_orders)
r = sub.add_parser("report"); r.add_argument("--news", default="news.json.gz")
r.add_argument("--out", default="paper_result.json"); r.set_defaults(f=cmd_report)
a = ap.parse_args()
a.f(a)
