#!/usr/bin/env python3
"""Taiwan-stock weekly rotation strategy + event-driven derisk, with backtest.

DESIGN NOTES (the parts that decide whether the result means anything)

* No look-ahead. Every decision made on date D uses only data with date <= D,
  and is EXECUTED at the next session's OPEN. Signals never touch same-bar close.
* No survivorship bias. The universe is rebuilt from what actually traded on each
  date, so delisted names are present until the day they stop trading.
* Dividend adjusted. TWSE closes are unadjusted and Taiwan pays out Jul-Sep --
  inside the window. We build a back-adjust factor from the ex-rights table so a
  4% yield is not scored as a 4% crash (and does not trip a stop-loss).
* Costs are charged on every fill: fee 0.1425% x discount (both sides),
  0.3% transaction tax (sell side, 0.1% for ETFs), plus slippage. Min fee NT$20.

The signal blend is deliberately plain -- momentum + institutional flow + a retail
-leverage penalty, all gated by trend and a market-regime throttle. On one year of
data anything more elaborate is curve-fitting.
"""
import sqlite3, math, json, argparse
from collections import defaultdict
from news_signal import load_news_sentiment
from kline_signal import week_groups, month_groups, period_candles, kline_score

# ---------------------------------------------------------------- parameters
P = dict(
    top_n=6,                 # positions held (Sam 2026-08-17: keep 3-6 for monitoring;
                             # 6 chosen -- at 3 names, shifting the pick window by one
                             # swung the year from +87% to -13%, i.e. pure noise)
    lookback_mom=60,         # momentum window (trading days)
    mom_skip=5,              # skip most recent days (short-term reversal)
    ma_trend=60,             # trend gate
    ma_slow=200,             # regime filter
    chip_fgn_win=20,         # foreign net-buy window
    chip_tru_win=10,         # investment-trust net-buy window
    chip_dlr_win=10,         # dealer (自營商) net-buy window. Shorter than the foreign
                             # window on purpose: proprietary desks turn over far faster
                             # than foreign funds, so a 20d sum mostly cancels itself out.
    chip_fgnp_win=20,        # window for foreign-buying PERSISTENCE (see W["fgnp"])
    margin_win=20,           # retail margin growth window
    vol_win=20,
    min_turnover=50e6,       # NT$ 20d median -- must absorb our size
    min_price=10.0,
    mom_cap=None,            # entry filter: skip a NEW name whose raw momentum z-score
                             # exceeds this (blow-off top). None = off. Held names exempt.
    hold_buffer=0,           # rank hysteresis: keep an incumbent that slipped to within
                             # top_n+hold_buffer instead of churning it. 0 = old rotation.
    swap_wed_fri=False,      # active-sleeve swap cadence. False=Fri only (proven;
                             # +51% Sharpe 1.04). True=Wed+Fri (Sam asked, but measured
                             # -12% Sharpe -0.37 -- momentum edge dies on the churn).

    # risk/quality guards (Sam 2026-08-19, after 7610 聯友金屬-創 was picked on raw
    # momentum, filled day-1 @+4% gap, then reversed -9.6% to the -8% stop). Both
    # default OFF so the engine is byte-identical until a run opts in; both are
    # honestly backtestable (price/vol only, point-in-time). Hand-set, NOT fitted.
    # (a) risk-adjusted momentum: rank on momentum PER UNIT of recent volatility, so a
    #     vertical high-vol blow-off (7610: mom 0.93 with vol 0.079) stops out-ranking a
    #     steadier lower-vol climber. Changes SELECTION only; conviction sizing already
    #     divides the WEIGHT by vol separately, so this is a different axis, not a re-hit.
    mom_risk_adj=True,       # LIVE (Sam 2026-08-19): zscore(mom / max(vol,0.02)) instead of
                             # zscore(mom). Backtest +42.7%->+44.4%, Sharpe 1.32->1.67, vol
                             # 32.8%->27.1%, MDD -20.7%->-19.2%; cut 7610-style blow-off buys 10->6.
    # (b) volatility ceiling: hard-drop any name whose recent daily vol exceeds this from
    #     the investable universe. Targets RISK, not price -- keeps Sam's high-price
    #     momentum names, cuts only the wild ones. None/0 = off.
    vol_ceiling=None,        # e.g. 0.06 ~= drop the top-vol tail (7610 was 0.079)
    max_weight=None,         # per-name cap; None = derive from top_n (see eff_max_w)
    rank_offset=0,           # test-only: start the pick window at rank N+1
    lot_size=1,              # odd-lot (零股) fills (Sam 2026-08-17, reverses the earlier 100).
                             # Whole lots (100) forced a price-cap universe filter -- any name
                             # whose ONE lot exceeded the per-name budget got EXCLUDED, dropping
                             # exactly the high-priced high-momentum stocks Sam wants kept
                             # ("避免單價因素排除上漲動能個股"). Odd lots remove that unit-price
                             # bias entirely (rebalance sets max_px -> inf, so no name is dropped
                             # for price) and also end the lot-rounding cash drag. Cost: thinner
                             # intraday odd-lot liquidity / wider spreads, covered roughly by the
                             # 0.1% slippage (disclosed as possibly insufficient in extremes).
                             # NOTE (Sam 2026-08-31): lot_size stays 1 only to keep the universe
                             # open (max_px -> inf). Actual fill granularity is snap_sh(): a buy
                             # OVER one 張 (>1000 股) rounds to whole 1000-share lots; <=1 lot
                             # stays 零股. So high-price names still enter via odd-lot, but any
                             # sizeable position trades in clean 張.
    # position sizing (Sam, 2026-08-17): don't split the budget equally -- put more
    # capital on the higher-conviction, lower-risk names, bounded so it never turns
    # into a single-name bet. All pre-set, NOT fitted to this sample. See target_weights().
    size_mode="conviction",  # "conviction" (risk/opportunity weighted) | "equal" (old behaviour)
    conv_tau=0.6,            # softmax temperature in composite-score units (smaller = more concentrated)
    conv_risk_parity=True,   # divide conviction by recent volatility (opportunity per unit risk)
    conv_max_weight=0.25,    # hard cap on any one name, as a fraction of the invested sleeve
    conv_min_weight=0.08,    # floor so a picked name is not dust (keeps 3-6 names meaningful)
    # laddered (階梯式) entry/exit (Sam 2026-08-17: "在信心不夠高情況下用階梯式買進賣出").
    # Rather than jump straight to the full conviction target, a LOW-confidence pick is
    # built up over several tranches -- the weaker the composite score, the more tranches
    # -- so a marginal name is only tested with a partial position and added to as it keeps
    # confirming; on a soft "fell out of top-N" drop it is scaled OUT tranche by tranche,
    # not dumped. HARD risk exits (stop / trailing / emergency) are NEVER laddered -- those
    # still liquidate in full in step(). Applied as a time-ramp ON TOP of target_weights
    # (staged = full × filled/total tranches); with ladder_enable off, staged == full and
    # behaviour is byte-identical to immediate fills. Hand-set, NOT fitted.
    ladder_enable=True,
    ladder_max_tranches=3,   # most tranches, used for the lowest-conviction names
    ladder_full_score=1.5,   # composite score at/above which a name goes to full in one shot
    ladder_exit=True,        # also scale OUT over tranches on a soft (non-risk) drop
    # weekly K-line tilt on the holding proportion (Sam 2026-08-17: "個股同時參考一週
    # K線圖分析，決定持有比例"). Reads candle anatomy of the last few weekly candles and
    # nudges each pick's conviction weight up (buyers in control) or down (rejected at
    # highs). SIZING ONLY -- it never changes which names are selected. Point-in-time
    # (price only), so it is honestly backtestable; hand-set, NOT fitted. See kline_signal.py.
    kline_win=8,             # weekly candles to analyse (ISO weeks up to the decision day)
    kline_tilt=0.5,          # sensitivity: weight *= exp(kline_tilt * score), score in [-1,1]
    # monthly K-line tilt on the holding proportion (Sam 2026-08-17: "個股同時參考一個月
    # K線圖分析，決定持有比例"). Same candle-anatomy read as the weekly layer but on calendar
    # -month candles -- the slower trend-confirmation layer that stacks with the weekly
    # tilt. Gentler sensitivity than weekly so the two together can't over-concentrate;
    # the per-name cap/floor still bounds the result. Point-in-time, hand-set, NOT fitted.
    mkline_win=6,            # monthly candles to analyse (calendar months up to the decision day)
    mkline_tilt=0.35,        # sensitivity: weight *= exp(mkline_tilt * score), score in [-1,1]
    # information side (Sam 2026-08-17, REVISED): news is NOT in the decision score.
    # Historical headlines cannot be aligned to "what was knowable at date D" without
    # look-ahead, and a sentiment score fitted that way would silently inflate the
    # backtest. So news stays a DISPLAY-ONLY panel for manual review -- computed for
    # the picks table, never fed into `score` or the conviction weight.
    news_win=5,              # trading-day lookback for the news panel
    news_decay=0.7,          # per-day recency decay on older headlines
    news_scale=3.0,          # divisor mapping raw polarity -> ~[-3,3] display units
    stop_loss=-0.12,         # hard stop from entry (Sam 2026-09-01: widened -8%->-12%.
                             # -8% shook names out on TW mid/small-cap daily noise -- ~49%
                             # of stop-outs recovered above the exit within 20 sessions.
                             # -12% lifts win rate 44%->51% AND return +51%->+67%, Sharpe
                             # 1.04->1.24, PF 1.58->1.74; consistent in BOTH year sub-splits,
                             # sentinel CLEAN ratio 34%. MDD -16.6%->-17.1% (marginal).)
    trail_stop=-0.15,        # trailing stop from peak (widened -12%->-15% with the above)
    stop_cooldown=10,        # sessions a stopped-out name is benched (anti-whipsaw)
    crash_day=-0.035,        # market 1-day drop -> full derisk
    crash_dd=-0.12,          # portfolio drawdown -> full derisk
    emg_cooldown=10,         # sessions benched after an emergency exit
    fee_rate=0.001425,
    fee_discount=1.0,        # 1.0 = no broker discount (conservative)
    tax_rate=0.003,
    tax_rate_etf=0.001,
    slippage=0.001,
    min_fee=20.0,
    capital=1_000_000.0,
    market_proxy="0050",
    # large-cap sleeve (Sam 2026-08-31: the new NT$1M runs 大型股 only). OFF by default so
    # the existing mid/small sleeve, the backtest and the sentinel are byte-identical.
    # The DB carries no market-cap column, so size is proxied by 20d median turnover
    # (成交值): the highest-turnover common shares ARE the 權值/大型股. When on, the
    # rebalance universe is trimmed to the top `large_top_k` names by that proxy.
    large_cap=False,
    large_top_k=50,          # keep the top-50 by 20d median turnover as the "大型股" pool
)

# dlr = 自營商 (broker proprietary desks), the third leg of 三大法人. The column has
# always been fetched and stored; it was simply never scored. Weight 0.0 keeps the
# score byte-identical to every prior run until a measurement earns it a weight.
# fgnp = foreign-buying PERSISTENCE: the share of sessions in the window that were
# net-buy days, centred to [-1,1]. A distinct claim from W["fgn"], which is a
# magnitude sum and can be carried by one block trade -- this asks whether the
# buying was steady. Weight 0.0 until measured.
# dlr_self / dlr_hedge = 自營商 split (Sam 2026-09-18): 自行買賣 (proprietary desks'
# directional view) vs 避險 (hedging against warrants they issued -- non-directional
# by construction). Decision log D5: the aggregate dealer_net tested as pure noise
# in both directions, plausibly because the hedge leg dilutes any directional
# signal. Both 0.0 until measured; the aggregate key stays for comparability.
W = dict(mom=0.35, fgn=0.30, tru=0.25, margin=-0.10, dlr=0.0, fgnp=0.0,
         dlr_self=0.0, dlr_hedge=0.0)


def eff_max_w():
    """Per-name cap. It must scale with top_n: a fixed 20% cap silently strands
    cash the moment the book holds fewer than 5 names (at 4 names equal weight is
    25%, so the cap binds and 20% of the account never gets invested). 10% headroom
    over equal weight leaves room for the top-up and for drift between rebalances."""
    return P["max_weight"] if P["max_weight"] else 1.10 / max(1, P["top_n"])


def _clamp_normalize(w, lo, hi, iters=32):
    """Project weights onto {sum == 1, lo <= w <= hi} by iterative water-filling:
    clamp the out-of-band names, then rescale the rest to fill what's left, repeat."""
    w = dict(w)
    for _ in range(iters):
        fixed, used = set(), 0.0
        for c, v in w.items():
            if v <= lo:
                w[c] = lo; fixed.add(c); used += lo
            elif v >= hi:
                w[c] = hi; fixed.add(c); used += hi
        free = [c for c in w if c not in fixed]
        if not free:
            break
        rem = 1.0 - used
        fs = sum(w[c] for c in free) or 1.0
        moved = False
        for c in free:
            nv = max(0.0, w[c] / fs * rem)
            moved = moved or abs(nv - w[c]) > 1e-12
            w[c] = nv
        if not moved:
            break
    s = sum(w.values()) or 1.0
    return {c: v / s for c, v in w.items()}


def target_weights(tgt, score, vol, expo, kline=None, mkline=None):
    """Position sizing. Instead of an equal split, weight each pick by opportunity
    (softmax of its composite score) tilted for risk (inverse recent volatility) and
    for the weekly + monthly K-line reads, then bound every name to [conv_min_weight,
    conv_max_weight] of the invested sleeve so concentration can't become a
    single-name bet. Returns each name's target as a fraction of TOTAL equity -- the
    fractions sum to `expo` (the regime exposure), leaving 1-expo in cash.

    `kline` / `mkline` (optional {code: strength in [-1,1]}) tilt the holding
    proportion: weight *= exp(kline_tilt * wk) * exp(mkline_tilt * mth). The two
    timeframes stack multiplicatively; both move size only, never selection.

    Computed at DECISION time (when the scores exist) and stored on `pending`; the
    fill just reads it. That keeps sizing on the same side of the look-ahead line as
    the stock selection."""
    tgt = list(tgt)
    n = len(tgt)
    if n == 0:
        return {}
    kline = kline or {}
    mkline = mkline or {}
    if P.get("size_mode") == "equal":
        w = {c: 1.0 / n for c in tgt}
    else:
        mx = max(score.get(c, 0.0) for c in tgt)
        tau = max(1e-6, P["conv_tau"])
        raw = {}
        for c in tgt:
            conv = math.exp((score.get(c, 0.0) - mx) / tau)        # opportunity
            if P.get("conv_risk_parity", True):
                conv /= max(vol.get(c, 0.02), 0.005)               # per unit of risk
            conv *= math.exp(P["kline_tilt"] * kline.get(c, 0.0))  # weekly-chart tilt
            conv *= math.exp(P["mkline_tilt"] * mkline.get(c, 0.0))  # monthly-chart tilt
            raw[c] = conv
        s = sum(raw.values()) or 1.0
        w = {c: raw[c] / s for c in tgt}
    lo = min(P["conv_min_weight"], 0.9 / n)      # stay feasible for a small book
    hi = max(P["conv_max_weight"], 1.05 / n)
    w = _clamp_normalize(w, lo, hi)
    return {c: w[c] * expo for c in tgt}


def ladder_tranches(score_val):
    """How many tranches to build (or unwind) a position in, from conviction. A high
    composite score -> 1 (take the full position at once); the weaker the score, the
    more tranches, up to ladder_max_tranches -- so low-confidence picks are entered and
    exited gradually. Returns 1 when laddering is disabled."""
    maxt = max(1, int(P.get("ladder_max_tranches", 1)))
    full = P.get("ladder_full_score", 1.5)
    if not P.get("ladder_enable") or maxt <= 1 or full <= 0 or score_val >= full:
        return 1
    frac = max(0.0, min(1.0, (full - score_val) / full))
    return 1 + round((maxt - 1) * frac)


# ---------------------------------------------------------------- data load
def load(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    px, chip, mgn = defaultdict(dict), defaultdict(dict), defaultdict(dict)
    for r in con.execute("SELECT * FROM price"):
        px[r["code"]][r["date"]] = dict(o=r["open"], h=r["high"], l=r["low"],
                                        c=r["close"], v=r["turnover"], name=r["name"])
    cols = [r[1] for r in con.execute("PRAGMA table_info(chip)")]
    has_split = "dealer_self" in cols      # False on a DB built before 2026-09-18
    for r in con.execute("SELECT * FROM chip"):
        chip[r["code"]][r["date"]] = dict(f=r["foreign_net"] or 0.0,
                                          t=r["trust_net"] or 0.0,
                                          d=r["dealer_net"] or 0.0,
                                          ds=(r["dealer_self"] if has_split else None),
                                          dh=(r["dealer_hedge"] if has_split else None))
    for r in con.execute("SELECT * FROM margin"):
        mgn[r["code"]][r["date"]] = r["margin_bal"] or 0.0
    ex = defaultdict(dict)
    for r in con.execute("SELECT * FROM exright"):
        if r["prev_close"] and r["ref_price"] and r["prev_close"] > 0:
            ex[r["code"]][r["date"]] = r["ref_price"] / r["prev_close"]
    dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM price ORDER BY date")]
    con.close()
    return px, chip, mgn, ex, dates


def adj_factors(px, ex, dates, limit=0.11, log=None):
    """Back-adjust factor per (code,date) so corporate actions leave no fake gap.

    Two sources:
      1. TWSE's ex-rights/ex-dividend table (TWT49U).
      2. SPLITS, which that table does NOT carry. We detect them from market
         structure: Taiwan enforces a +/-10% daily price limit, so an overnight
         move larger than that is *definitionally* a corporate action, not a
         price move. 0050 split 1:4 on 2025-06-18 (188.65 -> 47.57, -74.8%);
         left uncorrected it poisons every MA/momentum/vol figure that spans it
         -- and since 0050 is the regime proxy, it silently pins the whole
         strategy to risk-off exposure.
    """
    fac, found = {}, []
    for code, series in px.items():
        evs = dict(ex.get(code, {}))
        ds = [d for d in dates if d in series]
        for i in range(1, len(ds)):
            d0, d1 = ds[i - 1], ds[i]
            c0, c1 = series[d0].get("c"), series[d1].get("c")
            if not c0 or not c1 or c0 <= 0:
                continue
            r = c1 / c0
            if abs(r - 1.0) > limit and d1 not in evs:
                evs[d1] = r
                found.append((code, d1, c0, c1, r))
        if not evs:
            continue
        f, out = 1.0, {}
        for d in reversed(dates):
            out[d] = f
            if d in evs:                      # crossing back over an ex-date
                f *= evs[d]
        fac[code] = out
    if log is not None:
        log.extend(found)
    return fac


class Px:
    """Price accessor returning dividend-adjusted values."""
    def __init__(self, px, fac):
        self.px, self.fac = px, fac

    def get(self, code, date, field="c"):
        r = self.px.get(code, {}).get(date)
        if not r or r.get(field) is None:
            return None
        if field in ("o", "h", "l", "c"):
            return r[field] * self.fac.get(code, {}).get(date, 1.0)
        return r[field]

    def raw(self, code, date, field="c"):
        r = self.px.get(code, {}).get(date)
        return None if not r else r.get(field)


# ---------------------------------------------------------------- helpers
def zscore(d):
    vs = [v for v in d.values() if v is not None and math.isfinite(v)]
    if len(vs) < 5:
        return {k: 0.0 for k in d}
    m = sum(vs) / len(vs)
    sd = math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs)) or 1.0
    return {k: (0.0 if v is None or not math.isfinite(v) else
                max(-3.0, min(3.0, (v - m) / sd))) for k, v in d.items()}


def is_common(code):
    """Common shares only: 4 digits, 1101-9999. Drops ETFs(00xx), warrants(6+
    chars), TDRs(91xx), preferred(letter suffix)."""
    return len(code) == 4 and code.isdigit() and 1101 <= int(code) <= 9999


def swap_window(dates, di, wed_fri=False):
    """True if session dates[di] is a holding-swap window -- decide now, fill next
    open. wed_fri=False (DEFAULT): Fri only, the proven momentum cadence. wed_fri=True
    (Sam 2026-09-01 "每週三，週五進行持有交換窗口"): also the mid-week Wed window.

    NOTE measured: doubling the ACTIVE momentum sleeve to Wed+Fri halves its edge
    (full-window backtest +51% -> -12%, Sharpe 1.04 -> -0.37, PF 1.58 -> 0.91) --
    the weekly-momentum signal needs the hold; a 2-day churn cuts winners early and
    doubles cost. So the active sleeve stays Fri-only unless explicitly overridden.
    The passive 0050 core is cost-insensitive, so Wed+Fri is harmless there.

    Holiday-safe: uses the ALREADY-KNOWN next session, never looks ahead. Fires on
    the last session on-or-before Wed (mid-week) and on the week's last session
    (Fri). If Wed/Fri is a holiday it falls back to the nearest earlier session --
    can only ever miss a window, never fire early. Live tail (no next session yet):
    the calendar Wed(2)/Fri(4)."""
    import datetime as _dt
    wd = _dt.date(*map(int, dates[di].split("-"))).weekday()
    if di + 1 < len(dates):
        nxt = _dt.date(*map(int, dates[di + 1].split("-"))).weekday()
        crosses_week = nxt < wd            # next session starts a new week -> Fri window
        if not wed_fri:
            return crosses_week
        crosses_wed = wd <= 2 <= nxt - 1   # last session on-or-before Wed -> Wed window
        return crosses_week or crosses_wed
    return wd in (2, 4) if wed_fri else wd == 4


BOARD_LOT = 1000                         # 一張 = 1000 股


def snap_sh(sh):
    """Trade granularity (Sam 2026-08-31): a purchase LARGER than one board lot
    (>1000 股) executes in whole 1000-share 張; anything one lot or smaller stays
    odd-lot (零股), so high-price names aren't priced out of the universe (keeps the
    2026-08-17 odd-lot universe fix intact). Applies to buys, trims and top-ups."""
    sh = int(math.floor(sh))
    return (sh // BOARD_LOT) * BOARD_LOT if sh >= BOARD_LOT else sh


# ---------------------------------------------------------------- signals
def build_signals(P_, chip, mgn, dates, di, universe, news=None):
    """Score every candidate using data strictly up to dates[di]."""
    d = dates[di]
    news = news or {}
    mom, fgn, tru, dlr, fgp, mar, vol = {}, {}, {}, {}, {}, {}, {}
    dls, dlh = {}, {}
    for code in universe:
        s = P_.get(code, d)
        i0 = di - P["lookback_mom"]
        p0 = P_.get(code, dates[i0]) if i0 >= 0 else None
        p1 = P_.get(code, dates[di - P["mom_skip"]]) if di - P["mom_skip"] >= 0 else None
        if not (s and p0 and p1 and p0 > 0):
            continue
        mom[code] = p1 / p0 - 1.0

        # institutional flow, normalised by the stock's own turnover so a big
        # name and a small name are comparable
        turn = sum(P_.get(code, dates[j], "v") or 0.0
                   for j in range(max(0, di - P["chip_fgn_win"] + 1), di + 1)) or 1.0
        f = sum((chip.get(code, {}).get(dates[j], {}) or {}).get("f", 0.0)
                for j in range(max(0, di - P["chip_fgn_win"] + 1), di + 1))
        t = sum((chip.get(code, {}).get(dates[j], {}) or {}).get("t", 0.0)
                for j in range(max(0, di - P["chip_tru_win"] + 1), di + 1))
        dl = sum((chip.get(code, {}).get(dates[j], {}) or {}).get("d", 0.0)
                 for j in range(max(0, di - P["chip_dlr_win"] + 1), di + 1))
        # 自營商 split legs: same 10d turnover-normalised construction as dlr.
        # Missing (pre-split-era rows) contributes 0 -- coverage is reported by
        # exp_dealer_split.py, not silently filled here.
        dsl = sum(((chip.get(code, {}).get(dates[j], {}) or {}).get("ds") or 0.0)
                  for j in range(max(0, di - P["chip_dlr_win"] + 1), di + 1))
        dhl = sum(((chip.get(code, {}).get(dates[j], {}) or {}).get("dh") or 0.0)
                  for j in range(max(0, di - P["chip_dlr_win"] + 1), di + 1))
        # persistence: how many of the window's sessions were net-buy days. Only
        # days the stock actually has a chip row count, so a thinly-reported name
        # is not scored as "never bought".
        pj = [(chip.get(code, {}).get(dates[j]) or {}).get("f")
              for j in range(max(0, di - P["chip_fgnp_win"] + 1), di + 1)]
        pj = [v for v in pj if v is not None]
        fgp[code] = (2.0 * sum(1 for v in pj if v > 0) / len(pj) - 1.0) if pj else 0.0

        fgn[code] = f * s / turn
        tru[code] = t * s / turn
        dlr[code] = dl * s / turn
        dls[code] = dsl * s / turn
        dlh[code] = dhl * s / turn

        # retail leverage build-up = crowding = penalty
        m_now = mgn.get(code, {}).get(d)
        j0 = max(0, di - P["margin_win"])
        m_old = mgn.get(code, {}).get(dates[j0])
        mar[code] = ((m_now - m_old) / m_old) if (m_now and m_old and m_old > 100) else 0.0

        rets = []
        for j in range(max(1, di - P["vol_win"] + 1), di + 1):
            a, b = P_.get(code, dates[j]), P_.get(code, dates[j - 1])
            if a and b and b > 0:
                rets.append(a / b - 1.0)
        vol[code] = (math.sqrt(sum(r * r for r in rets) / len(rets)) if rets else 0.02) or 0.02

    # news sentiment, recency-decayed over the window ending at the decision day.
    # DISPLAY ONLY -- this is computed for the manual-review panel and is deliberately
    # NOT added to `score`. Feeding historical headlines into the decision would inject
    # look-ahead (they can't be aligned to point-in-time availability) and inflate the
    # backtest, so news never moves selection or the conviction weight.
    nws = {}
    for c in mom:
        tot = 0.0
        nd = news.get(c)
        if nd:
            for j in range(max(0, di - P["news_win"] + 1), di + 1):
                v = nd.get(dates[j])
                if v:
                    tot += v * (P["news_decay"] ** (di - j))
        nws[c] = tot

    # weekly + monthly K-line strength, SIZING ONLY (not added to score). Both built
    # from adjusted prices up to the decision day, so no look-ahead. Applied as
    # conviction tilts in target_weights() -- they decide holding proportion, never
    # selection. Weekly = tactical layer, monthly = slower trend-confirmation layer.
    wgrp = week_groups(dates, di, P["kline_win"])
    kln = {c: kline_score(period_candles(P_, dates, wgrp, c)) for c in mom}
    mgrp = month_groups(dates, di, P["mkline_win"])
    klm = {c: kline_score(period_candles(P_, dates, mgrp, c)) for c in mom}

    # (a) risk-adjusted momentum -- rank momentum per unit of vol (floor the divisor so a
    # near-flat ultra-low-vol name can't get an inflated ratio). z-score normalises scale.
    mom_in = ({c: mom[c] / max(vol.get(c, 0.02), 0.02) for c in mom}
              if P.get("mom_risk_adj") else mom)
    zm, zf, zt, zg = zscore(mom_in), zscore(fgn), zscore(tru), zscore(mar)
    zd, zp = zscore(dlr), zscore(fgp)
    zds, zdh = zscore(dls), zscore(dlh)
    # (b) volatility ceiling -- drop the wildest names from ranking entirely.
    vc = P.get("vol_ceiling") or 0.0
    score = {c: W["mom"] * zm[c] + W["fgn"] * zf[c] + W["tru"] * zt[c]
                + W["margin"] * zg[c] + W.get("dlr", 0.0) * zd[c]
                + W.get("fgnp", 0.0) * zp[c]
                + W.get("dlr_self", 0.0) * zds[c] + W.get("dlr_hedge", 0.0) * zdh[c]
             for c in mom if not (vc and vol.get(c, 0.0) > vc)}
    return score, vol, dict(mom=mom, fgn=fgn, tru=tru, dlr=dlr, fgnp=fgp,
                            dlr_self=dls, dlr_hedge=dlh,
                            mar=mar, news=nws, kline=kln, kline_m=klm)


def regime(P_, dates, di):
    """Market throttle from the 0050 proxy: below MA200 -> 40%, below MA60 -> 70%."""
    mp = P["market_proxy"]
    c = P_.get(mp, dates[di])
    if not c:
        return 1.0, "unknown"
    def ma(n):
        vs = [P_.get(mp, dates[j]) for j in range(max(0, di - n + 1), di + 1)]
        vs = [v for v in vs if v]
        return sum(vs) / len(vs) if vs else None
    m60, m200 = ma(P["ma_trend"]), ma(P["ma_slow"])
    if m200 and c < m200:
        return 0.40, "risk-off (below MA200)"
    if m60 and c < m60:
        return 0.70, "caution (below MA60)"
    return 1.0, "risk-on"


# ---------------------------------------------------------------- engine
class Engine:
    """The decision core, shared by the backtest and forward paper trading.

    Paper trading MUST run the identical rules or the two silently diverge and
    the backtest stops describing the thing actually being traded. So there is
    exactly one implementation and both callers drive it one session at a time.

    Persistent state is keyed by DATE, never by session index: extending history
    backwards (which we do, to warm up MA200) renumbers every index and would
    otherwise silently corrupt saved cooldowns and halts.
    """

    def __init__(self, ctx, capital):
        self.ctx = ctx
        self.capital = capital
        self.cash = capital
        self.pos = {}
        self.pending = None
        self.peak_eq = capital
        self.trig_peak = capital
        self.halt_until = None      # date string
        self.halted = False
        self.cooldown = {}          # code -> date string
        self.ladder = {}            # code -> {stage, tranches, full}: laddered build/unwind state
        self.trades, self.equity, self.events, self.weekly = [], [], [], []

    # ---- persistence ------------------------------------------------------
    def dump(self):
        return dict(capital=self.capital, cash=self.cash, pos=self.pos,
                    pending=self.pending, peak_eq=self.peak_eq, trig_peak=self.trig_peak,
                    halt_until=self.halt_until, halted=self.halted, cooldown=self.cooldown,
                    ladder=self.ladder,
                    trades=self.trades, equity=self.equity, events=self.events,
                    weekly=self.weekly)

    def restore(self, st):
        for k, v in st.items():
            setattr(self, k, v)
        return self

    # ---- helpers ----------------------------------------------------------
    def _sess(self, di, n):
        ds = self.ctx["dates"]
        return ds[min(di + n, len(ds) - 1)]

    def _mv(self, d):
        P_ = self.ctx["P_"]
        return sum(p["sh"] * (P_.get(c, d) or p["last"]) for c, p in self.pos.items())

    def _sell(self, code, sh, price, date, why):
        gross = sh * price * (1 - P["slippage"])
        fee = max(P["min_fee"], gross * P["fee_rate"] * P["fee_discount"])
        tax = gross * (P["tax_rate_etf"] if not is_common(code) else P["tax_rate"])
        self.cash += gross - fee - tax
        self.trades.append(dict(date=date, code=code, side="SELL", sh=round(sh),
                                price=round(price, 2), cost=round(fee + tax), why=why))

    def _buy_sh(self, code, sh, price, date, why):
        """Buy an EXACT share count (caller has already lot-snapped it)."""
        sh = int(sh)
        if sh <= 0:
            return 0
        p_eff = price * (1 + P["slippage"])
        gross = sh * p_eff
        fee = max(P["min_fee"], gross * P["fee_rate"] * P["fee_discount"])
        if gross + fee > self.cash:
            return 0
        self.cash -= gross + fee
        self.trades.append(dict(date=date, code=code, side="BUY", sh=round(sh),
                                price=round(p_eff, 2), cost=round(fee), why=why))
        return sh

    def _buy(self, code, budget, price, date, why):
        p_eff = price * (1 + P["slippage"])
        return self._buy_sh(code, snap_sh(budget / (p_eff * (1 + P["fee_rate"]))),
                            price, date, why)

    # ---- one session ------------------------------------------------------
    def step(self, di, last=False):
        P_, chip, mgn = self.ctx["P_"], self.ctx["chip"], self.ctx["mgn"]
        dates, px = self.ctx["dates"], self.ctx["raw_px"]
        d = dates[di]

        # 1. fill yesterday's decisions at today's OPEN
        if self.pending:
            self._fill(di, d)

        # 2. mark to market
        for c, p in self.pos.items():
            v = P_.get(c, d)
            if v:
                p["last"] = v
                p["peak"] = max(p["peak"], v)
        eq = self.cash + self._mv(d)
        self.peak_eq = max(self.peak_eq, eq)
        self.trig_peak = max(self.trig_peak, eq)
        self.equity.append(dict(date=d, equity=round(eq), cash=round(self.cash),
                                npos=len(self.pos), dd=round(eq / self.peak_eq - 1.0, 4)))
        if last:
            return

        # 3. EMERGENCY derisk -- every day, not just at rebalance
        mkt_ret = None
        a, b = P_.get(P["market_proxy"], d), P_.get(P["market_proxy"], dates[di - 1])
        if a and b:
            mkt_ret = a / b - 1.0
        # Armed off trig_peak, NOT the all-time peak. Against the all-time peak the
        # condition stays true every day once breached, so the rule re-fires forever:
        # buy the book Monday, dump it Tuesday, repeat. Resetting on each fire makes
        # it an event rather than a latch.
        dd = eq / self.trig_peak - 1.0
        armed = (self.halt_until is None) or (d > self.halt_until)
        if armed and self.pos and ((mkt_ret is not None and mkt_ret <= P["crash_day"])
                                   or dd <= P["crash_dd"]):
            why = ("market -%.1f%% in one day" % (abs(mkt_ret) * 100)
                   if (mkt_ret is not None and mkt_ret <= P["crash_day"])
                   else "portfolio drawdown %.1f%%" % (dd * 100))
            self.pending = dict(sell=list(self.pos), buy=[], expo=0.0, decided=d,
                                why={c: "EMERGENCY: " + why for c in self.pos})
            self.halted = True
            self.halt_until = self._sess(di, P["emg_cooldown"])
            self.trig_peak = eq
            self.events.append(dict(date=d, kind="EMERGENCY_EXIT", detail=why,
                                    n=len(self.pos), equity=round(eq)))
            return

        stops = {}
        for c, p in list(self.pos.items()):
            r_ent = p["last"] / p["entry"] - 1.0
            r_pk = p["last"] / p["peak"] - 1.0
            if r_ent <= P["stop_loss"]:
                stops[c] = "stop-loss %.1f%%" % (r_ent * 100)
            elif r_pk <= P["trail_stop"]:
                stops[c] = "trailing stop %.1f%% off peak" % (r_pk * 100)
        if stops:
            for c in stops:                    # bench it, or the next rebalance
                self.cooldown[c] = self._sess(di, P["stop_cooldown"])
            self.pending = dict(sell=list(stops), buy=[], expo=0.0, decided=d, why=stops)
            self.events.append(dict(date=d, kind="STOP", detail="; ".join(
                "%s %s" % (k, v) for k, v in stops.items()), n=len(stops), equity=round(eq)))
            return

        # 4. TWICE-WEEKLY rebalance -- decide at the Wed & Fri swap windows, fill
        #    next open (Sam 2026-09-01: "每週三，週五進行持有交換窗口").
        import datetime as _dt
        if not swap_window(dates, di, P.get("swap_wed_fri", False)):
            return
        self.rebalance(di, d)

    def rebalance(self, di, d, force=False):
        """Score the market and stage next-session orders. force=True ignores the
        weekly cadence and any post-emergency halt (used to open a fresh account)."""
        P_, chip, mgn = self.ctx["P_"], self.ctx["chip"], self.ctx["mgn"]
        dates, px = self.ctx["dates"], self.ctx["raw_px"]
        expo, reg = regime(P_, dates, di)
        if self.halted and not force:
            if expo < 1.0 or (self.halt_until and d <= self.halt_until):
                self.weekly.append(dict(date=d, regime=reg, exposure=0.0, picks=[],
                                        buy=[], sell=[], note="halted after emergency exit"))
                return
            self.halted = False

        # With a fixed lot size, a name is only investable if a SINGLE lot fits
        # inside the per-name budget. At NT$125k/name and 100-share lots that caps
        # the share price at NT$1,250 -- otherwise one lot would blow the target
        # weight (or, for the priciest names, the entire account). This is a
        # tradability constraint like the liquidity floor, not a return tweak.
        lot = max(1, int(P["lot_size"]))
        eq_est = self.cash + sum(p["sh"] * (P_.get(c2, d) or p["last"])
                                 for c2, p in self.pos.items())
        # A name is investable if one lot fits the LARGEST slot it could be given.
        # Under conviction sizing that is the per-name cap, not equal weight -- using
        # the equal-weight budget here would wrongly exclude a pricey high-conviction
        # candidate, i.e. exactly the name Sam wants room to overweight.
        if P.get("size_mode") == "equal":
            per_cap = min((eq_est * expo) / P["top_n"], eq_est * eff_max_w())
        else:
            per_cap = eq_est * expo * max(P["conv_max_weight"], 1.05 / P["top_n"])
        max_px = per_cap / lot if lot > 1 else float("inf")

        uni, medtv = [], {}
        for code, series in px.items():
            if not is_common(code) or d not in series:
                continue
            c = P_.get(code, d)
            if not c or c < P["min_price"]:
                continue
            if c > max_px:                    # one lot would not fit the budget
                continue
            tv = sorted(P_.get(code, dates[j], "v") or 0.0
                        for j in range(max(0, di - 19), di + 1))
            if not tv or tv[len(tv) // 2] < P["min_turnover"]:
                continue
            ma = [P_.get(code, dates[j]) for j in range(max(0, di - P["ma_trend"] + 1), di + 1)]
            ma = [v for v in ma if v]
            if not ma or c < sum(ma) / len(ma):          # trend gate
                continue
            cd = self.cooldown.get(code)
            if cd and d <= cd and code not in self.pos:  # recently stopped out
                continue
            uni.append(code); medtv[code] = tv[len(tv) // 2]
        # large-cap sleeve: keep only the top-K names by 20d median turnover (成交值),
        # the size proxy for 權值/大型股 (see P["large_cap"]). Held names are kept in the
        # pool so a leader that slips a few ranks isn't force-sold on a size technicality.
        if P.get("large_cap"):
            keep = set(sorted(uni, key=lambda c2: -medtv[c2])[:P["large_top_k"]])
            uni = [c2 for c2 in uni if c2 in keep or c2 in self.pos]

        score, vol, raw = build_signals(P_, chip, mgn, dates, di, uni, self.ctx.get("news"))
        _off = P.get("rank_offset", 0)
        srt = sorted(score, key=lambda c: -score[c])
        # MOMENTUM CEILING entry filter (Sam 2026-09-01, low win rate). Stop-outs
        # enter with much higher raw momentum than winners (blow-off tops that
        # reverse into the stop -- the 7610 pattern). Skip a NEW name whose raw
        # momentum z-score exceeds mom_cap; a name already HELD is exempt so a real
        # runner is never force-sold. mom_cap=None -> off (byte-identical).
        _cap = P.get("mom_cap")
        if _cap is not None:
            _mz = raw.get("mom", {})
            srt = [c for c in srt if _mz.get(c, 0.0) <= _cap or c in self.pos]
        cutoff = _off + P["top_n"]
        strict = srt[_off:cutoff]
        # RANK HYSTERESIS (Sam 2026-09-01 "換股窗口也可以選擇持續持有"): a held name that
        # slips out of the strict top-N but is still within top_n+hold_buffer keeps its
        # slot instead of being churned; fresh names only fill slots the incumbents leave
        # empty. hold_buffer=0 -> exactly the old rotation (byte-identical). This is what
        # lets a twice-weekly window HOLD rather than swap on rank noise.
        buf = P.get("hold_buffer", 0)
        if buf:
            rank_of = {c: i for i, c in enumerate(srt)}
            book, seen = [], set()
            for c in sorted((h for h in self.pos if _off <= rank_of.get(h, 1 << 30) < cutoff + buf),
                            key=lambda h: rank_of[h]):               # incumbents within the band keep their slot
                if len(book) < P["top_n"]:
                    book.append(c); seen.add(c)
            for c in strict:                                          # fill the rest with the best fresh names
                if len(book) >= P["top_n"]:
                    break
                if c not in seen:
                    book.append(c); seen.add(c)
            ranked = book
        else:
            ranked = strict
        full_wts = target_weights(ranked, score, vol, expo,
                                  raw.get("kline"), raw.get("kline_m"))     # conviction/risk/K-line sizing
        wgrp = week_groups(dates, di, P["kline_win"])
        mgrp = month_groups(dates, di, P["mkline_win"])
        cndl = {c: period_candles(P_, dates, wgrp, c) for c in ranked}      # weekly chart
        mcndl = {c: period_candles(P_, dates, mgrp, c) for c in ranked}     # monthly chart

        # LADDERED (階梯式) staging. Ramp each name toward its FULL conviction target over
        # tranches set by conviction (low score -> more tranches). A name held & still
        # selected advances one tranche/week; a soft-dropped name winds down one tranche
        # /week (scale_out) instead of being dumped. Hard risk exits never reach here --
        # they are handled in step() and always liquidate in full. With ladder_enable off,
        # wts == full_wts and every name is at stage 1/1, i.e. identical to immediate fills.
        rset = set(ranked)
        wts = dict(full_wts)
        stage_info, scale_out = {}, []
        if P.get("ladder_enable"):
            new_ladder = {}
            for c in ranked:
                tr = ladder_tranches(score.get(c, 0.0))
                prev = self.ladder.get(c)
                stage = min(tr, (prev["stage"] + 1) if prev else 1)         # +1 tranche per week still selected
                new_ladder[c] = dict(stage=stage, tranches=tr, full=full_wts.get(c, 0.0))
                wts[c] = full_wts.get(c, 0.0) * stage / tr
                stage_info[c] = (stage, tr)
            if P.get("ladder_exit", True):
                for c in list(self.pos):                                    # soft drops: wind down, don't dump
                    if c in rset:
                        continue
                    prev = self.ladder.get(c)
                    if prev and prev["stage"] > 1:
                        stage = prev["stage"] - 1
                        new_ladder[c] = dict(stage=stage, tranches=prev["tranches"], full=prev["full"])
                        wts[c] = prev["full"] * stage / prev["tranches"]
                        scale_out.append(c)
                        stage_info[c] = (stage, prev["tranches"])
            self.ladder = new_ladder

        target = ranked + scale_out
        to_sell = [c for c in self.pos if c not in set(target)]
        to_buy = [c for c in ranked if c not in self.pos]
        self.pending = dict(sell=to_sell, buy=to_buy, target=target, weights=wts,
                            expo=expo, decided=d,
                            why={**{c: "dropped from top-%d" % P["top_n"] for c in to_sell},
                                 **{c: "scale-out %d/%d, wt %.0f%%"
                                    % (stage_info[c][0], stage_info[c][1], wts.get(c, 0) * 100)
                                    for c in scale_out},
                                 **{c: "rank %d, score %.2f, wt %.0f%%%s"
                                    % (ranked.index(c) + 1, score[c], wts.get(c, 0) * 100,
                                       (" (階梯 %d/%d)" % stage_info[c]) if c in stage_info else "")
                                    for c in ranked}})
        self.weekly.append(dict(date=d, regime=reg, exposure=expo,
                                picks=[dict(code=c, name=(px[c][d]["name"] or "").strip(),
                                            score=round(score[c], 3),
                                            weight=round(wts.get(c, 0.0), 4),
                                            weight_full=round(full_wts.get(c, 0.0), 4),
                                            stage=("%d/%d" % stage_info[c]) if c in stage_info else "",
                                            mom=round(raw["mom"].get(c, 0), 4),
                                            fgn=round(raw["fgn"].get(c, 0), 4),
                                            tru=round(raw["tru"].get(c, 0), 4),
                                            news=round(raw.get("news", {}).get(c, 0), 4),
                                            kline=round(raw.get("kline", {}).get(c, 0), 3),
                                            kcandles=cndl.get(c, []),
                                            kline_m=round(raw.get("kline_m", {}).get(c, 0), 3),
                                            mcandles=mcndl.get(c, []),
                                            vol=round(vol.get(c, 0.0), 4),
                                            price=round(P_.get(c, d) or 0, 2))
                                      for c in ranked],
                                buy=to_buy, sell=to_sell,
                                scale_out=[dict(code=c, name=(px.get(c, {}).get(d, {}) or {}).get("name", "").strip(),
                                                stage="%d/%d" % stage_info[c]) for c in scale_out]))

    def _fill(self, di, d):
        P_ = self.ctx["P_"]
        pend = self.pending
        # STRUCTURAL NO-LOOK-AHEAD INVARIANT. Every fill must land on a strictly
        # later session than the decision that produced it. Same-bar execution is
        # the easiest look-ahead to reintroduce by accident (one refactor that
        # calls rebalance() and _fill() on the same index does it silently), and
        # it is the one bias a backtest cannot reveal by looking at the returns.
        # Cheap enough to assert on every single fill, so it always runs.
        if pend.get("decided") and not (d > pend["decided"]):
            raise AssertionError(
                "LOOK-AHEAD: fill on %s from a decision made on %s (must be strictly later)"
                % (d, pend["decided"]))

        def op(c):
            return P_.get(c, d, "o") or P_.get(c, d)

        for code in pend["sell"]:
            if code in self.pos:
                o = op(code) or self.pos[code]["last"]
                self._sell(code, self.pos[code]["sh"], o, d,
                           pend["why"].get(code, "rebalance"))
                self.pos.pop(code)
                self.ladder.pop(code, None)      # fully out -> forget its ladder state

        # Size each target to its conviction/risk weight -- trim the overweight,
        # top up the underweight. Sizing new buys off leftover cash makes weight
        # depend on trade order: a name bought in a cash-rich week ends up several
        # times heavier than one bought while fully invested. That is a sizing
        # artefact, not a view -- so we drive every name to a stored target instead.
        tgt = pend.get("target") or []
        if tgt:
            eq_now = self.cash + sum(p["sh"] * (op(c) or p["last"])
                                     for c, p in self.pos.items())
            wts = pend.get("weights") or {}
            # fall back to equal split only if an old pending had no weights stored
            pers = {c: eq_now * wts.get(c, pend["expo"] / len(tgt)) for c in tgt}
            for code in tgt:
                o = op(code)
                if not o:
                    continue
                per = pers[code]
                o_eff = o * (1 + P["slippage"]) * (1 + P["fee_rate"])
                have = self.pos[code]["sh"] if code in self.pos else 0
                want = snap_sh(per / o_eff)          # rule-conforming TARGET share count
                if abs((want - have) * o) < per * 0.15:   # no-trade band: churn costs money
                    continue
                if want > have:
                    # buy toward the target, but keep the RESULTING holding conforming
                    # (>1000 -> whole 張, <=1000 -> odd) even when cash is the binding limit.
                    afford = math.floor(self.cash / o_eff)
                    buy_sh = snap_sh(have + min(want - have, afford)) - have
                    sh = self._buy_sh(code, buy_sh, o, d, pend["why"].get(code, "entry"))
                    if sh:
                        if code in self.pos:
                            p = self.pos[code]
                            p["entry"] = (p["entry"] * p["sh"] + o * sh) / (p["sh"] + sh)
                            p["sh"] += sh
                        else:
                            self.pos[code] = dict(sh=sh, entry=o, peak=o, last=o)
                elif code in self.pos:                # want < have -> trim to target
                    cut = self.pos[code]["sh"] - want
                    if cut > 0:
                        self._sell(code, cut, o, d, "trim to target weight")
                        self.pos[code]["sh"] -= cut
                        if self.pos[code]["sh"] <= 0:
                            self.pos.pop(code)
                            self.ladder.pop(code, None)

            # Top-up pass. Lot granularity strands cash: a NT$938 name takes one
            # 100-share lot (NT$93.8k) against a NT$125k target, so the book can
            # sit ~10% in cash purely as a rounding artefact. Repeatedly add one
            # lot to whichever holding is furthest below ITS OWN target -- but never
            # past +2% of that target, because one lot of a NT$500 name is 38% of the
            # budget and a loose tolerance turns rounding into a large active bet.
            lot = BOARD_LOT              # top-ups add whole 張 (Sam 2026-08-31)
            for _ in range(len(tgt) * 3):
                best, gap = None, 0.0
                for code in tgt:
                    o = op(code)
                    if not o or code not in self.pos:
                        continue
                    held_sh = self.pos[code]["sh"]
                    if held_sh < lot or held_sh % lot != 0:   # only whole-lot names:
                        continue                              # +1張 keeps the total conforming
                    per = pers[code]
                    cost = lot * o * (1 + P["slippage"]) * (1 + P["fee_rate"])
                    held = held_sh * o
                    if (cost <= self.cash and held + lot * o <= per * 1.02
                            and per - held > gap):
                        best, gap = code, per - held
                if not best:
                    break
                o = op(best)
                sh = self._buy_sh(best, lot, o, d, "top-up to target weight")
                if not sh:
                    break
                pp = self.pos[best]
                pp["entry"] = (pp["entry"] * pp["sh"] + o * sh) / (pp["sh"] + sh)
                pp["sh"] += sh
        self.pending = None


def make_ctx(db, news_path="news.json.gz"):
    px, chip, mgn, ex, dates = load(db)
    return dict(P_=Px(px, adj_factors(px, ex, dates)), chip=chip, mgn=mgn,
                dates=dates, raw_px=px,
                news=load_news_sentiment(news_path, dates))


# ---------------------------------------------------------------- backtest
def backtest_ctx(ctx, start, end):
    """Backtest over a PRELOADED ctx -- lets a parameter search reuse one DB load
    across hundreds of runs instead of re-reading the DB every time."""
    dates = ctx["dates"]
    di_start = next(i for i, d in enumerate(dates) if d >= start)
    di_end = max(i for i, d in enumerate(dates) if d <= end)

    e = Engine(ctx, P["capital"])
    for di in range(di_start, di_end + 1):
        e.step(di, last=(di == di_end))

    return dict(equity=e.equity, trades=e.trades, weekly=e.weekly,
                events=e.events, px=ctx["P_"], dates=dates, final_pos=e.pos,
                chip=ctx["chip"], mgn=ctx["mgn"], raw_px=ctx["raw_px"],
                news=ctx.get("news"))


def backtest(db, start, end, verbose=True):
    return backtest_ctx(make_ctx(db), start, end)



# ---------------------------------------------------------------- holdings review
def review_holdings(res, holdings, asof=None):
    """Requirement 2: score what Sam actually owns on the same axes the strategy
    uses to pick, so 'why do I still hold this' has a numeric answer.

    holdings: [{code, shares, cost}]  (cost = average buy price, NT$/share)
    """
    P_, dates, chip, mgn = res["px"], res["dates"], res["chip"], res["mgn"]
    di = max(i for i, d in enumerate(dates) if d <= asof) if asof else len(dates) - 1
    d = dates[di]
    codes = [str(h["code"]).strip() for h in holdings]
    # Score against the WHOLE liquid cross-section, not just these few names.
    # The signals are z-scores, so ranking 3 holdings against each other yields
    # ~0 for everything and tells the reader nothing about where they stand.
    uni = set(codes)
    for c, series in P_.px.items():
        if is_common(c) and d in series and (P_.get(c, d, "v") or 0) >= P["min_turnover"]:
            uni.add(c)
    score, vol, raw = build_signals(P_, chip, mgn, dates, di, sorted(uni), res.get("news"))
    rank = {c: i + 1 for i, c in enumerate(sorted(score, key=lambda x: -score[x]))}
    nuni = len(score)

    out = []
    for h in holdings:
        c = str(h["code"]).strip()
        last = P_.get(c, d)
        name = (res["raw_px"].get(c, {}).get(d, {}) or {}).get("name", "") or ""
        # trend + regime context
        ma = [P_.get(c, dates[j]) for j in range(max(0, di - P["ma_trend"] + 1), di + 1)]
        ma = [v for v in ma if v]
        ma60 = sum(ma) / len(ma) if ma else None
        f20 = sum((chip.get(c, {}).get(dates[j], {}) or {}).get("f", 0.0)
                  for j in range(max(0, di - 19), di + 1))
        t20 = sum((chip.get(c, {}).get(dates[j], {}) or {}).get("t", 0.0)
                  for j in range(max(0, di - 19), di + 1))
        m_now = mgn.get(c, {}).get(d)
        m_old = mgn.get(c, {}).get(dates[max(0, di - 20)])
        mg = ((m_now / m_old - 1.0) if (m_now and m_old and m_old > 100) else None)

        cost = h.get("cost")
        pnl = (last / cost - 1.0) if (last and cost) else None
        flags, action = [], "HOLD"
        if last and ma60 and last < ma60:
            flags.append("below MA60 (trend gate fails)")
        if f20 < 0:
            flags.append("foreign net SELL 20d")
        if t20 < 0:
            flags.append("trust net SELL 20d")
        if mg is not None and mg > 0.15:
            flags.append("margin balance +%.0f%% 20d (retail crowding)" % (mg * 100))
        if pnl is not None and pnl <= P["stop_loss"]:
            flags.append("past %.0f%% stop-loss" % (P["stop_loss"] * 100))
            action = "CUT"
        elif len(flags) >= 2:
            action = "TRIM"
        elif score.get(c, 0) > 0.5 and not flags:
            action = "ADD-OK"

        out.append(dict(code=c, name=name.strip(), shares=h.get("shares"), cost=cost,
                        last=round(last, 2) if last else None,
                        value=round(last * h["shares"]) if (last and h.get("shares")) else None,
                        pnl_pct=pnl, score=round(score.get(c, 0.0), 3),
                        rank=rank.get(c), n_uni=nuni,
                        ma60=round(ma60, 2) if ma60 else None,
                        fgn20=round(f20), tru20=round(t20),
                        margin_chg=mg, vol=round(vol.get(c, 0) * math.sqrt(252), 3),
                        flags=flags, action=action))
    tot = sum(o["value"] or 0 for o in out)
    for o in out:
        o["weight"] = (o["value"] / tot) if (tot and o["value"]) else 0.0
    return dict(asof=d, rows=out, total_value=tot)
