#!/usr/bin/env python3
"""Passive large-cap CORE sleeve (Sam 2026-08-31: the new NT$1M runs 大型股 as a
buy-and-hold 0050 core with a regime throttle, NOT active stock rotation).

Why not the active engine: backtested over the same window, restricting the
mid/small rotation engine to the top-50 large caps returned +1.3% (Sharpe -0.01,
172 trades) vs simply holding 0050 at +103% (Sharpe 3.75). The chip/turnover
factor is meaningless among large caps and weekly momentum churn abandons the
megacap winners. So the large-cap 1M is a passive core: hold the 0050 proxy,
scaled by the same regime() throttle the active sleeve uses (below MA200 -> 40%,
below MA60 -> 70%), rebalanced on the Wed & Fri swap windows, filled next open.

Costs, lot snapping, weekly cadence and ETF tax mirror the main Engine exactly so
the two sleeves are directly comparable. State is DATE-keyed and lives in
paper_state_core.json, independent of the active sleeve.
"""
import datetime as _dt
import strategy as S

P = S.P


class CoreSleeve:
    def __init__(self, ctx, capital, proxy="0050", throttle=True):
        self.ctx = ctx
        self.capital = capital
        self.cash = capital
        self.proxy = proxy
        self.throttle = throttle
        self.pos = {}                 # {proxy: {sh, entry, peak, last}}
        self.pending = None           # {target_val, decided, why}
        self.peak_eq = capital
        self.trades, self.equity = [], []

    # ---- persistence ------------------------------------------------------
    def dump(self):
        return dict(capital=self.capital, cash=self.cash, proxy=self.proxy,
                    throttle=self.throttle, pos=self.pos, pending=self.pending,
                    peak_eq=self.peak_eq, trades=self.trades, equity=self.equity)

    def restore(self, st):
        for k, v in st.items():
            setattr(self, k, v)
        return self

    # ---- fills ------------------------------------------------------------
    def _open(self, d):
        return self.ctx["P_"].get(self.proxy, d, "o") or self.ctx["P_"].get(self.proxy, d)

    def _fill(self, di, d):
        pend = self.pending
        self.pending = None
        if not pend:
            return
        o = self._open(d)
        if not o:
            return
        have = self.pos[self.proxy]["sh"] if self.proxy in self.pos else 0
        eq = self.cash + have * o
        tgt_val = pend["target_val"]
        o_eff = o * (1 + P["slippage"]) * (1 + P["fee_rate"])
        want = S.snap_sh(tgt_val / o_eff)
        if abs((want - have) * o) < eq * 0.02:          # no-trade band
            return
        if want > have:
            afford = int((self.cash) / o_eff)
            buy = S.snap_sh(have + min(want - have, afford)) - have
            if buy <= 0:
                return
            p_eff = o * (1 + P["slippage"])
            gross = buy * p_eff
            fee = max(P["min_fee"], gross * P["fee_rate"] * P["fee_discount"])
            if gross + fee > self.cash:
                return
            self.cash -= gross + fee
            self.trades.append(dict(date=d, code=self.proxy, side="BUY", sh=round(buy),
                                    price=round(p_eff, 2), cost=round(fee), why=pend["why"]))
            if self.proxy in self.pos:
                p = self.pos[self.proxy]
                p["entry"] = (p["entry"] * p["sh"] + p_eff * buy) / (p["sh"] + buy)
                p["sh"] += buy
            else:
                self.pos[self.proxy] = dict(sh=buy, entry=p_eff, peak=o, last=o)
        else:                                            # trim toward target
            sell = have - want
            if sell <= 0:
                return
            gross = sell * o * (1 - P["slippage"])
            fee = max(P["min_fee"], gross * P["fee_rate"] * P["fee_discount"])
            tax = gross * (P["tax_rate_etf"] if not S.is_common(self.proxy) else P["tax_rate"])
            self.cash += gross - fee - tax
            self.trades.append(dict(date=d, code=self.proxy, side="SELL", sh=round(sell),
                                    price=round(o, 2), cost=round(fee + tax), why=pend["why"]))
            self.pos[self.proxy]["sh"] -= sell
            if self.pos[self.proxy]["sh"] <= 0:
                self.pos.pop(self.proxy)

    # ---- decision ---------------------------------------------------------
    def target_exposure(self, di):
        return S.regime(self.ctx["P_"], self.ctx["dates"], di)[0] if self.throttle else 1.0

    def rebalance(self, di, d, force=False):
        P_, dates = self.ctx["P_"], self.ctx["dates"]
        c = P_.get(self.proxy, d)
        if not c:
            return
        have = self.pos[self.proxy]["sh"] if self.proxy in self.pos else 0
        eq = self.cash + have * c
        expo = self.target_exposure(di)
        self.pending = dict(target_val=eq * expo, decided=d,
                            why="core %.0f%% (regime throttle)" % (expo * 100)
                                if self.throttle else "core 100%")

    def step(self, di, last=False):
        P_, dates = self.ctx["P_"], self.ctx["dates"]
        d = dates[di]
        if self.pending:
            self._fill(di, d)
        c = P_.get(self.proxy, d)
        if self.proxy in self.pos and c:
            self.pos[self.proxy]["last"] = c
            self.pos[self.proxy]["peak"] = max(self.pos[self.proxy]["peak"], c)
        eq = self.cash + (self.pos[self.proxy]["sh"] * (c or self.pos[self.proxy]["last"])
                          if self.proxy in self.pos else 0)
        self.peak_eq = max(self.peak_eq, eq)
        self.equity.append(dict(date=d, equity=round(eq), cash=round(self.cash),
                                npos=len(self.pos), dd=round(eq / self.peak_eq - 1.0, 4)))
        if last:
            return
        # twice-weekly cadence -- Wed & Fri swap windows, fill next open (Sam
        # 2026-09-01). The passive core is cost-insensitive, so Wed+Fri is free
        # here and lets the regime throttle react ~2 days faster than weekly.
        if S.swap_window(dates, di, wed_fri=True):
            self.rebalance(di, d)

    # ---- indicative order sheet for the next open -------------------------
    def order_sheet(self, decided_date):
        P_, dates = self.ctx["P_"], self.ctx["dates"]
        px = self.ctx["raw_px"]
        di = dates.index(decided_date)
        if di + 1 < len(dates):
            nxt = dates[di + 1]
        else:
            n = _dt.date(*map(int, decided_date.split("-"))) + _dt.timedelta(days=1)
            while n.weekday() >= 5:
                n += _dt.timedelta(days=1)
            nxt = n.isoformat() + " (next session)"
        rows = []
        if self.pending:
            c = P_.get(self.proxy, decided_date)
            have = self.pos[self.proxy]["sh"] if self.proxy in self.pos else 0
            o_eff = c * (1 + P["slippage"]) * (1 + P["fee_rate"])
            want = S.snap_sh(self.pending["target_val"] / o_eff)
            delta = want - have
            eq = self.cash + have * c
            if abs(delta * c) >= eq * 0.02:
                nm = (px.get(self.proxy, {}).get(decided_date, {}) or {}).get("name", "").strip()
                rows.append(dict(code=self.proxy, name=nm, sleeve="core",
                                 side="BUY" if delta > 0 else "SELL (trim)",
                                 shares=abs(delta), ref_price=round(c, 2),
                                 amount=round(abs(delta) * c), why=self.pending["why"]))
        return dict(decided=decided_date, fill_at=nxt, rows=rows)
