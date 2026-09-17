#!/usr/bin/env python3
"""Quantify the information side (news headlines) into a per-stock sentiment
score for the position-sizing logic (Sam 2026-08-17: "將資訊面量化為分數，放入
部位決定邏輯").

Design decisions worth keeping:
- Deterministic zh-TW finance lexicon, NO external calls. The devserver has no
  egress and the daily cron is unattended -- an LLM-in-the-loop scorer would be a
  hidden dependency that fails closed at 20:00 with nobody watching.
- Look-ahead safe by construction: each item is dated to the FIRST trading
  session on or after its publish date, so weekend/after-close news informs the
  next decision, never a past one. build_signals then only reads dates <= the
  decision day.
- The lexicon weights are PRE-SET, never tuned against the backtest sample --
  same discipline as every other parameter. There is also no year-long news
  archive to tune against: the live feed is a snapshot, so the signal is inert in
  the historical backtest and only takes effect forward. That is a feature here,
  not a gap -- there is nothing to overfit.
"""
import gzip, json, re, os

# zh-TW finance sentiment lexicon. 2+ char terms only -- single characters like
# 漲/跌/增 fire on unrelated words (增列預算, 下跌 vs 大跌) and manufacture noise.
POS = {
    "漲停": 1.6, "飆漲": 1.5, "大漲": 1.4, "勁揚": 1.2, "走高": 0.8,
    "創高": 1.3, "新高": 1.3, "突破": 1.0, "回升": 0.8,
    "優於預期": 1.5, "轉盈": 1.3, "獲利": 1.0, "成長": 1.0, "營收成長": 1.2,
    "看好": 1.1, "強勁": 1.1, "樂觀": 0.8, "受惠": 1.0, "利多": 1.2,
    "訂單": 0.8, "擴產": 0.9, "調升": 1.1, "買超": 1.0, "長約": 0.6,
    "奪冠": 0.7, "認購": 0.4, "續配": 0.4,
}
NEG = {
    "跌停": 1.6, "崩跌": 1.5, "重挫": 1.5, "大跌": 1.4,
    "低於預期": 1.5, "轉虧": 1.4, "虧損": 1.3, "衰退": 1.2, "下滑": 0.9,
    "下修": 1.4, "調降": 1.2, "減資": 1.1, "利空": 1.2, "賣壓": 1.1,
    "疲弱": 1.0, "警訊": 1.2, "示警": 1.2, "違約": 1.4, "裁員": 1.0,
    "停產": 1.2, "召回": 0.9, "賣超": 1.0, "風暴": 1.0, "認售": 0.4,
}

CODE_RE = re.compile(r"(\d{4})\s*-\s*TW")
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _pub_date(pub):
    """'Mon, 17 Aug 2026 15:26:14 +0800' -> '2026-08-17' (None on any surprise)."""
    try:
        p = pub.replace(",", "").split()
        return "%04d-%02d-%02d" % (int(p[3]), _MONTHS[p[2]], int(p[1]))
    except Exception:
        return None


def _polarity(text):
    """Signed sentiment of one text blob, clipped to +-3 so one ranty headline
    can't swamp the cross-section."""
    p = sum(w for k, w in POS.items() if k in text)
    n = sum(w for k, w in NEG.items() if k in text)
    return max(-3.0, min(3.0, p - n))


def load_news_sentiment(path, dates):
    """Return {code: {trade_date: summed_sentiment}}.

    Each item's polarity (title weighted 1.5x the summary) is attributed to every
    4-digit TWSE code it names, on the first trading session >= its publish date.
    """
    out = {}
    if not path or not os.path.exists(path):
        return out
    try:
        items = json.load(gzip.open(path, "rt", encoding="utf-8"))
    except Exception:
        return out
    for it in items:
        pd = _pub_date(it.get("pub", "") or "")
        if not pd:
            continue
        td = next((d for d in dates if d >= pd), None)   # snap forward, never back
        if not td:
            continue
        title, desc = it.get("title", "") or "", it.get("desc", "") or ""
        pol = _polarity(title) * 1.5 + _polarity(desc)
        if pol == 0:
            continue
        for c in set(CODE_RE.findall(title + " " + desc)):
            out.setdefault(c, {})[td] = out.setdefault(c, {}).get(td, 0.0) + pol
    return out
