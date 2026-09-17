#!/usr/bin/env python3
"""未來函數 (look-ahead bias) — 建構四種常見版本，量化每一種偷到多少報酬。

用途不是作弊，是當「上界哨兵」：先做一個明知作弊的版本，如果誠實版的績效
逼近它，就代表誠實版漏了資料。這是偵測 leakage 最有效的一招。

四種（由輕到重）：
  A 同K棒成交   用決策當天的收盤價成交 —— 你在算出訊號的同一瞬間就成交了
  B 停損抓最低   停損用當天最低價出場 —— 假設你每次都賣在當日最低點
  C 隔日排名     用「明天」的資料選股
  D 完美預知     直接用「下週實際報酬」選股
"""
import copy, json
import strategy as S
from report import metrics, trade_stats

DB, START, END = "twstock.db", "2025-08-14", "2026-08-14"
BASE = copy.deepcopy(S.P)


def restore():
    for k in BASE:
        S.P[k] = BASE[k]


class PrevCloseAsOpen:
    """A: 讓「開盤價」回傳前一個交易日的收盤價 = 在決策當根K棒成交。"""
    def __init__(self, P_, dates):
        self.P_, self.dates = P_, dates
        self.idx = {d: i for i, d in enumerate(dates)}

    def get(self, c, d, f="c"):
        if f == "o":
            i = self.idx.get(d, 0)
            return self.P_.get(c, self.dates[i - 1], "c") if i > 0 else self.P_.get(c, d, "o")
        return self.P_.get(c, d, f)

    def raw(self, c, d, f="c"):
        return self.P_.raw(c, d, f)


def perfect_intraday(e):
    """B: 買進成交在當日最低價、賣出成交在當日最高價 = 完美日內擇時。
    要做到這件事，你必須事先知道當天的高低點 —— 這才是乾淨的未來函數。
    （第一版寫成買賣都用最低價，買便宜、賣吃虧互相抵消，示範不出東西。）"""
    ob, os_ = e._buy, e._sell
    def buy(code, budget, price, date, why):
        lo = e.ctx["P_"].get(code, date, "l") or price
        return ob(code, budget, min(lo, price), date, why)
    def sell(code, sh, price, date, why):
        hi = e.ctx["P_"].get(code, date, "h") or price
        return os_(code, sh, max(hi, price), date, why)
    e._buy, e._sell = buy, sell
    return e


def run(label, ctx_mod=None, signal_mod=None, engine_mod=None):
    restore()
    ctx = S.make_ctx(DB)
    dates = ctx["dates"]
    if ctx_mod:
        ctx = ctx_mod(ctx)
    orig = S.build_signals
    if signal_mod:
        S.build_signals = signal_mod(ctx, orig)
    try:
        di0 = next(i for i, d in enumerate(dates) if d >= START)
        di1 = max(i for i, d in enumerate(dates) if d <= END)
        e = S.Engine(ctx, BASE["capital"])
        if engine_mod:
            e = engine_mod(e)
        for di in range(di0, di1 + 1):
            e.step(di, last=(di == di1))
        m = metrics(e.equity, label, base=BASE["capital"])
        ts = trade_stats(e.trades, ctx["P_"])
        return dict(label=label, ret=m["total_return"], sharpe=m["sharpe"],
                    mdd=m["mdd"], n=ts["n"], wr=ts["win_rate"])
    finally:
        S.build_signals = orig


def future_rank(shift):
    """C/D: 用未來 `shift` 個交易日之後的實際報酬排名。"""
    def maker(ctx, orig):
        dates = ctx["dates"]
        def f(P_, chip, mgn, ds, di, uni):
            sc, vol, raw = orig(P_, chip, mgn, ds, di, uni)
            j = min(di + shift, len(dates) - 1)
            fut = {}
            for c in sc:
                a, b = P_.get(c, ds[di]), P_.get(c, ds[j])
                if a and b and a > 0:
                    fut[c] = b / a - 1.0
            return (fut or sc), vol, raw
        return f
    return maker


rows = [run("誠實版（D+1 開盤成交）")]
rows.append(run("A 同K棒成交（決策日收盤價）",
                ctx_mod=lambda c: {**c, "P_": PrevCloseAsOpen(c["P_"], c["dates"])}))
rows.append(run("B 完美日內擇時（買最低/賣最高）", engine_mod=perfect_intraday))
rows.append(run("C 用「明日」資料選股", signal_mod=future_rank(1)))
rows.append(run("D 完美預知（用下週實際報酬選股）", signal_mod=future_rank(5)))

print("%-30s %10s %8s %10s %8s %8s" % ("版本", "總報酬", "Sharpe", "最大回撤", "成交筆", "勝率"))
print("-" * 78)
base = rows[0]["ret"]
for r in rows:
    tag = "" if r is rows[0] else "   (+%.0fpp)" % ((r["ret"] - base) * 100)
    print("%-30s %+9.1f%% %8.2f %9.1f%% %8d %7.0f%%%s"
          % (r["label"], r["ret"] * 100, r["sharpe"], r["mdd"] * 100, r["n"], r["wr"] * 100, tag))
json.dump(rows, open("lookahead_demo.json", "w"), ensure_ascii=False)
