#!/usr/bin/env python3
"""Fold the attribution diagnostics + market-breadth context into result.json.

Without breadth context a reader sees '+41% vs +104%' and concludes the signals
are broken. The truer statement is narrower: the index was carried by a few
mega-caps this strategy structurally never ranks, while the median stock did
+37%. Both facts belong on the page.
"""
import json, statistics as st
import strategy as S

res = json.load(open("result.json", encoding="utf-8"))
diag = json.load(open("diagnostics.json", encoding="utf-8"))

px, chip, mgn, ex, dates = S.load("twstock.db")
P = S.Px(px, S.adj_factors(px, ex, dates))
d0, d1 = res["meta"]["start"], res["meta"]["end"]
d0 = min(d for d in dates if d >= d0)
d1 = max(d for d in dates if d <= d1)


def ret(c):
    a, b = P.get(c, d0), P.get(c, d1)
    return (b / a - 1) if (a and b and a > 0) else None


rs = []
for c in px:
    if not S.is_common(c) or d0 not in px[c] or d1 not in px[c]:
        continue
    if (P.get(c, d1, "v") or 0) < S.P["min_turnover"]:
        continue
    r = ret(c)
    if r is not None:
        rs.append(r)
rs.sort()
bm = ret(S.P["market_proxy"]) or 0.0
names = {"2330": "台積電", "2454": "聯發科", "2308": "台達電", "2317": "鴻海", "2382": "廣達"}

res["diagnostics"] = diag
res["context"] = dict(
    n=len(rs), median=st.median(rs), mean=st.mean(rs),
    p25=rs[len(rs) // 4], p75=rs[3 * len(rs) // 4], p90=rs[int(.9 * len(rs))],
    bench=bm, beat_share=sum(1 for r in rs if r > bm) / len(rs),
    megacaps=[dict(code=c, name=n, ret=ret(c)) for c, n in names.items() if ret(c) is not None],
    strategy=res["metrics"]["total_return"],
    picked_2330=sum(1 for w in res["weekly"] for p in w["picks"] if p["code"] == "2330"),
    weeks=len(res["weekly"]))
json.dump(res, open("result.json", "w", encoding="utf-8"), ensure_ascii=False)
print("context: n=%d median=%+.1f%% bench=%+.1f%% beat=%.0f%% 2330 picked %d/%d weeks"
      % (len(rs), st.median(rs) * 100, bm * 100,
         100 * res["context"]["beat_share"], res["context"]["picked_2330"], res["context"]["weeks"]))
