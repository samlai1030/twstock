#!/usr/bin/env python3
"""Multi-timeframe K-line (candlestick) technical read, folded into POSITION SIZING only.

Sam 2026-08-17: "個股同時參考一週K線圖分析，決定持有比例" and then "個股同時參考一個月
K線圖分析，決定持有比例." Both timeframes feed the SAME sizing logic: the weekly candle
read is the tactical layer, the monthly candle read is the slower trend-confirmation
layer. Unlike news, price is perfectly point-in-time -- every candle (weekly OR
monthly) is built ONLY from sessions <= the decision day, so this is honestly
backtestable and DOES move the historical result (nothing to align, no look-ahead).

Design choices that keep it honest, not curve-fit:
  * It reads candle ANATOMY -- where the period closes inside its range, body vs wick,
    period-over-period consistency -- deliberately NOT raw return. Momentum already
    carries return; a return factor here would just double-count it. The same
    kline_score() reads a list of weekly OR monthly candles; only the grouping differs.
  * It is a SIZING tilt, not a selection signal. Sam asked it to decide 持有比例
    (holding proportion), so it nudges the conviction weight of names already picked;
    it never changes WHICH names are picked. Weekly and monthly tilts stack
    (multiplicatively), then the per-name cap/floor still bounds concentration.
  * Sub-weights are hand-set and round on purpose. They are NOT fitted to the sample
    -- see the v0-optimization finding (optimizing this 14-month window overfits).
  * Prices are dividend-ADJUSTED (the Px accessor), so an ex-dividend gap never
    forges a bearish candle.
"""
import datetime as _dt


def _pkey(d, kind):
    y, m, day = map(int, d.split("-"))
    if kind == "month":
        return (y, m)
    iy, iw, _ = _dt.date(y, m, day).isocalendar()   # ISO (year, week)
    return (iy, iw)


def period_groups(dates, di, nperiods, kind="week"):
    """Day-index lists for the last `nperiods` calendar periods ending at (and
    including) di. kind='week' -> ISO weeks, kind='month' -> calendar months. A
    Friday-close (or month-end) decision therefore gets a complete current candle;
    earlier periods are whole."""
    groups, cur, key = [], [], None
    for i in range(di + 1):
        k = _pkey(dates[i], kind)
        if k != key:
            if cur:
                groups.append(cur)
            cur, key = [], k
        cur.append(i)
    if cur:
        groups.append(cur)
    return groups[-nperiods:]


def week_groups(dates, di, nweeks):
    return period_groups(dates, di, nweeks, "week")


def month_groups(dates, di, nmonths):
    return period_groups(dates, di, nmonths, "month")


def period_candles(P_, dates, groups, code):
    """Dividend-adjusted OHLC for one code over the given period (week/month) groups."""
    out = []
    for g in groups:
        o = h = l = c = None
        for i in g:
            d = dates[i]
            cc = P_.get(code, d, "c")
            if cc is None:
                continue
            oo, hh, ll = P_.get(code, d, "o"), P_.get(code, d, "h"), P_.get(code, d, "l")
            if o is None:
                o = oo or cc
            h = (hh or cc) if h is None else max(h, hh or cc)
            l = (ll or cc) if l is None else min(l, ll or cc)
            c = cc
        if None not in (o, h, l, c) and h >= l:
            out.append(dict(o=round(o, 2), h=round(h, 2), l=round(l, 2), c=round(c, 2)))
    return out


def kline_score(candles):
    """Candle strength in [-1, 1] for a list of weekly OR monthly candles. Positive =
    buyers in control of the chart. Timeframe-agnostic: the caller supplies whichever
    candles it built.

    Needs >= 3 candles or it returns 0 (neutral) -- a sizing tilt must not fire on a
    name too new to have a chart on this timeframe."""
    if len(candles) < 3:
        return 0.0

    def rng(k):
        return max(k["h"] - k["l"], 1e-9)

    recent = candles[-3:]
    # 1. close position inside the period range: closing in the upper half = strength
    pos = sum((k["c"] - k["l"]) / rng(k) for k in recent) / len(recent)     # [0,1]
    # 2. body direction & dominance: a long green real body = conviction
    body = sum((k["c"] - k["o"]) / rng(k) for k in recent) / len(recent)    # ~[-1,1]
    # 3. upper-wick rejection over the last 2 periods: selling into strength = penalty
    last2 = candles[-2:]
    upw = sum((k["h"] - max(k["o"], k["c"])) / rng(k) for k in last2) / len(last2)  # [0,1]
    # 4. consistency: share of green periods across the whole window (centered)
    green = sum(1 for k in candles if k["c"] > k["o"]) / len(candles)       # [0,1]

    s = 0.40 * (2 * pos - 1) + 0.30 * body + 0.20 * (2 * green - 1) - 0.30 * upw
    return max(-1.0, min(1.0, s))
