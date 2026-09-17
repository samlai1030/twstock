#!/usr/bin/env python3
"""Two-sleeve reporting (Sam 2026-08-31).

  merge_report.py init-core --capital 1000000   open the passive 0050 core sleeve
  merge_report.py step-core                      advance the core through new sessions
  merge_report.py report                         merge active + core -> paper_result.json

The account is a barbell of two hard-segregated NT$1M sleeves:
  * ACTIVE  (paper_state.json)      -- the mid/small momentum engine (unchanged)
  * CORE    (paper_state_core.json) -- passive 0050 with a regime throttle

The new NT$1M is a mid-stream CONTRIBUTION, not a return, so account-level metrics
are time-weighted (TWR): the deposit day is neutralised (r = (V - flow)/V_prev - 1)
and the benchmark receives the identical cash-flow timing. Absolute equity curves
still show the real NAV stepping up on the deposit day -- honest, and both the
strategy and 0050 step together so the comparison stays fair.
"""
import json, os, math, argparse, datetime as dt
import strategy as S
import core_sleeve as C
from report import trade_stats

A_STATE = "paper_state.json"
C_STATE = "paper_state_core.json"
TD = 252
RF = 0.015


def load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def save(p, st):
    json.dump(st, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ---- TWR metrics with mid-stream contributions --------------------------------
def twr_metrics(curve, flows, label):
    """curve: [{date,equity}], flows: {date: amount} deposited at that date's close.
    Returns time-weighted performance that neutralises contributions."""
    if len(curve) < 3:
        return {}
    eq = [c["equity"] for c in curve]
    dates = [c["date"] for c in curve]
    rets = []
    for i in range(1, len(eq)):
        if eq[i - 1] <= 0:
            continue
        flow = flows.get(dates[i], 0)
        rets.append((eq[i] - flow) / eq[i - 1] - 1.0)
    # TWR growth index (starts at 1.0)
    idx, v = [1.0], 1.0
    for r in rets:
        v *= (1 + r); idx.append(v)
    n = len(eq)
    yrs = n / TD
    tot = idx[-1] - 1.0
    cagr = idx[-1] ** (1 / yrs) - 1.0 if yrs > 0 else 0.0
    mu = sum(rets) / len(rets) if rets else 0.0
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) if len(rets) > 1 else 0.0
    vol = sd * math.sqrt(TD)
    sharpe = (cagr - RF) / vol if vol > 1e-9 else 0.0
    dn = [r for r in rets if r < 0]
    dsd = math.sqrt(sum(r * r for r in dn) / len(dn)) * math.sqrt(TD) if dn else 0.0
    sortino = (cagr - RF) / dsd if dsd > 1e-9 else 0.0
    peak, mdd, mdd_at = idx[0], 0.0, dates[0]
    for i, x in enumerate(idx):
        peak = max(peak, x)
        d = x / peak - 1.0
        if d < mdd:
            mdd, mdd_at = d, dates[min(i, len(dates) - 1)]
    return dict(label=label, start=dates[0], end=dates[-1], days=n,
                start_eq=round(eq[0]), end_eq=round(eq[-1]), total_return=tot,
                cagr=cagr, vol=vol, sharpe=sharpe, sortino=sortino,
                mdd=mdd, mdd_at=mdd_at, calmar=(cagr / abs(mdd) if mdd < -1e-9 else 0.0),
                best_day=max(rets) if rets else 0, worst_day=min(rets) if rets else 0,
                pos_days=sum(1 for r in rets if r > 0) / len(rets) if rets else 0)


def bench_curve(ctx, dates, di0, di1, flows_by_date, proxy):
    """Buy-and-hold the proxy, receiving the same cash flows on the same dates
    (bought at that day's open), so it is the honest 'just buy 0050' twin."""
    P_ = ctx["P_"]
    cash, sh, out = 0.0, 0.0, []
    for di in range(di0, di1 + 1):
        d = dates[di]
        o = P_.get(proxy, d, "o") or P_.get(proxy, d)
        c = P_.get(proxy, d) or o
        add = flows_by_date.get(d, 0)
        if add and o:
            cash += add
            p_eff = o * (1 + S.P["slippage"])
            buy = math.floor(cash / (p_eff * (1 + S.P["fee_rate"])))
            if buy > 0:
                cash -= buy * p_eff + max(S.P["min_fee"], buy * p_eff * S.P["fee_rate"])
                sh += buy
        out.append(dict(date=d, equity=round(cash + sh * (c or 0)), cash=round(cash), npos=1, dd=0))
    return out


def cmd_init_core(a):
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    d = max(x for x in dates if x <= a.asof) if a.asof else dates[-1]
    di = dates.index(d)
    core = C.CoreSleeve(ctx, a.capital, proxy=a.proxy, throttle=not a.no_throttle)
    core.rebalance(di, d, force=True)
    # seed the deposit day: 1M sits in cash until the 0050 order fills next open,
    # so the contribution shows in the account from day one (subsequent step-core
    # calls only append dates AFTER this, so it is never double-counted).
    core.equity.append(dict(date=d, equity=round(a.capital), cash=round(a.capital), npos=0, dd=0.0))
    st = dict(engine=core.dump(), last_date=d, opened=d, capital=a.capital,
              created=dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    save(C_STATE, st)
    sheet = core.order_sheet(d)
    print("opened CORE sleeve: NT$%s (%s, throttle=%s), fills at %s open"
          % (f"{a.capital:,.0f}", a.proxy, not a.no_throttle, sheet["fill_at"]))
    for r in sheet["rows"]:
        print("  %-11s %-6s %7d sh @ ~%8.2f = NT$%9s  %s"
              % (r["side"], r["code"], r["shares"], r["ref_price"], f"{r['amount']:,}", r["why"]))


def cmd_step_core(a):
    st = load(C_STATE)
    if not st:
        return print("no core sleeve -- run init-core first")
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    core = C.CoreSleeve(ctx, st["engine"]["capital"]).restore(st["engine"])
    new = [d for d in dates if d > st["last_date"]]
    if not new:
        return print("core: no new sessions since", st["last_date"])
    for d in new:
        core.step(dates.index(d), last=False)
        print("core stepped", d, "equity NT$%s" % f"{core.equity[-1]['equity']:,}")
    st["engine"], st["last_date"] = core.dump(), new[-1]
    save(C_STATE, st)


def cmd_report(a):
    ctx = S.make_ctx(a.db)
    dates = ctx["dates"]
    # ---- ACTIVE sleeve -------------------------------------------------------
    sa = load(A_STATE)
    S.P["capital"] = sa["capital"]
    ea = S.Engine(ctx, sa["engine"]["capital"]).restore(sa["engine"])
    a_eq = ea.equity or [dict(date=sa["opened"], equity=sa["capital"], cash=sa["capital"], npos=0, dd=0.0)]
    # ---- CORE sleeve ---------------------------------------------------------
    sc = load(C_STATE)
    core = C.CoreSleeve(ctx, sc["engine"]["capital"]).restore(sc["engine"]) if sc else None
    c_eq = core.equity if (core and core.equity) else []
    inject_date = sc["opened"] if sc else None
    inject_amt = sc["capital"] if sc else 0

    # ---- combined absolute equity by date ------------------------------------
    a_by = {p["date"]: p for p in a_eq}
    c_by = {p["date"]: p for p in c_eq}
    all_dates = sorted(set(a_by) | set(c_by))
    combined, flows = [], {}
    for d in all_dates:
        av = a_by.get(d, {}).get("equity", 0)
        cv = c_by.get(d, {}).get("equity", 0)
        cash = a_by.get(d, {}).get("cash", 0) + c_by.get(d, {}).get("cash", 0)
        npos = a_by.get(d, {}).get("npos", 0) + c_by.get(d, {}).get("npos", 0)
        combined.append(dict(date=d, equity=av + cv, cash=cash, npos=npos, dd=0.0))
    if inject_date:
        flows[inject_date] = inject_amt
    # TWR drawdown back onto the displayed curve
    idx, v, peak = [], 1.0, 1.0
    prev = None
    for p in combined:
        if prev is not None and prev["equity"] > 0:
            r = (p["equity"] - flows.get(p["date"], 0)) / prev["equity"] - 1.0
            v *= (1 + r)
        peak = max(peak, v)
        p["dd"] = round(v / peak - 1.0, 4)
        prev = p

    di0 = dates.index(combined[0]["date"])
    di1 = dates.index(combined[-1]["date"])
    total_cap = sa["capital"] + (sc["capital"] if sc else 0)

    m = twr_metrics(combined, flows, "Paper (2-sleeve)")
    bflows = {combined[0]["date"]: sa["capital"]}
    if inject_date:
        bflows[inject_date] = inject_amt
    bench = bench_curve(ctx, dates, di0, di1, bflows, S.P["market_proxy"])
    mb = twr_metrics(bench, bflows, "0050")

    ts = trade_stats(ea.trades, ctx["P_"])       # active-sleeve round-trips only

    def pos_rows(pos, sleeve, last_date):
        rows = []
        for c, p in pos.items():
            nm = (ctx["raw_px"].get(c, {}).get(last_date, {}) or {}).get("name", "").strip()
            rows.append(dict(code=c, name=nm, sleeve=sleeve, sh=p["sh"],
                             entry=round(p["entry"], 2), last=round(p["last"], 2),
                             value=round(p["sh"] * p["last"]),
                             ret=p["last"] / p["entry"] - 1.0))
        return rows
    positions = pos_rows(ea.pos, "active", a_eq[-1]["date"])
    if core:
        positions += pos_rows(core.pos, "core", (c_eq[-1]["date"] if c_eq else combined[-1]["date"]))

    # merged order sheet (active + core), each row sleeve-tagged
    orders = json.load(open("paper_orders.json", encoding="utf-8")) if os.path.exists("paper_orders.json") else None
    if orders:
        for r in orders.get("rows", []):
            r.setdefault("sleeve", "active")
    if core:
        cs = core.order_sheet(sc["last_date"])
        if orders:
            # active often has nothing staged mid-week (it rebalances Fridays); when
            # the only live orders are the core's, adopt the core's fill timing for
            # the header so it doesn't show a stale "—".
            if not orders.get("rows") and cs["rows"]:
                orders["fill_at"] = cs["fill_at"]
                orders["decided"] = cs["decided"]
            orders["rows"] = orders.get("rows", []) + cs["rows"]
        else:
            orders = cs

    a_val = a_eq[-1]["equity"]
    c_val = c_eq[-1]["equity"] if c_eq else 0
    sleeves = [dict(name="active", label="中小型主動 α", value=a_val, base=sa["capital"],
                    ret=a_val / sa["capital"] - 1.0),
               dict(name="core", label="大型權值被動核心 (0050)", value=c_val,
                    base=(sc["capital"] if sc else 0),
                    ret=(c_val / sc["capital"] - 1.0) if sc and sc["capital"] else 0.0)]

    news = []
    if os.path.exists(a.news):
        import gzip
        news = json.load(gzip.open(a.news, "rt", encoding="utf-8"))[:40]

    # 集保籌碼分佈 for what we actually hold. DISPLAY ONLY -- never reaches `score`;
    # only one weekly snapshot exists so far and a weight needs a full-window plus
    # sub-period measurement (HANDOFF/03_DECISION_LOG.md D7). Wrapped because a TDCC
    # outage must not take the whole report down with it.
    tdcc_rows, tdcc_st = {}, {}
    try:
        import tdcc as _td
        tdcc_st = _td.status()
        tdcc_rows = _td.concentration([p["code"] for p in positions])
    except Exception as e:
        print("tdcc panel skipped:", type(e).__name__, e)

    out = dict(meta=dict(generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                         start=combined[0]["date"], end=combined[-1]["date"],
                         capital=total_cap, params=S.P, weights=S.W, mode="paper",
                         inject_date=inject_date, inject_amt=inject_amt),
               metrics=m, bench_metrics=mb,
               trade_stats={k: v for k, v in ts.items() if k != "closed"},
               closed=ts["closed"][-200:],
               total_cost=sum(t["cost"] for t in ea.trades) + (sum(t["cost"] for t in core.trades) if core else 0),
               equity=combined, bench=bench, weekly=ea.weekly, events=ea.events,
               trades=(ea.trades + (core.trades if core else []))[-300:],
               latest=(ea.weekly[-1] if ea.weekly else None),
               holdings=None, news=news, orders=orders, sleeves=sleeves,
               positions=positions, tdcc=tdcc_rows, tdcc_status=tdcc_st)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    print("wrote", a.out, "| sessions", len(combined),
          "| active NT$%s + core NT$%s = NT$%s"
          % (f"{a_val:,}", f"{c_val:,}", f"{a_val + c_val:,}"),
          "| TWR total %.2f%%" % (m.get("total_return", 0) * 100))


ap = argparse.ArgumentParser()
ap.add_argument("--db", default="twstock.db")
sub = ap.add_subparsers(dest="cmd", required=True)
ic = sub.add_parser("init-core")
ic.add_argument("--capital", type=float, default=1_000_000.0)
ic.add_argument("--proxy", default="0050"); ic.add_argument("--asof", default=None)
ic.add_argument("--no-throttle", action="store_true"); ic.set_defaults(f=cmd_init_core)
scp = sub.add_parser("step-core"); scp.set_defaults(f=cmd_step_core)
rp = sub.add_parser("report"); rp.add_argument("--news", default="news.json.gz")
rp.add_argument("--out", default="paper_result.json"); rp.set_defaults(f=cmd_report)
a = ap.parse_args()
a.f(a)
