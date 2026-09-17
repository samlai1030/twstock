# 03 — Decision log

**This is the expensive file.** The code can be re-read in an hour. This took a month
of measurement to produce. Every entry is something that was *tested*, not reasoned
about. Read it before changing a parameter, and especially before "improving" anything.

Format: what was asked → what was measured → what was decided.

---

## A. The meta-rules Sam set, that govern everything else

1. **Parameters were fixed before the first backtest, and are not tuned against the
   same year.** Sam stated this up front. Any change has to be justified by a
   mechanism, then measured full-window *and* split by sub-period — not chosen
   because it made the number go up.
2. **Sub-period split before believing any full-window optimum.** This rule exists
   because it caught a real one (§D2).
3. **A guard that has never fired is decoration.** Every guard in this system was
   fault-injected to prove the alarm actually triggers.
4. **A signal that cannot be point-in-time aligned must not enter the decision.**
   Display it, don't score it. (This killed the news signal — §C4.)

---

## B. The bugs that changed the answer

These are the ones where the *conclusion flipped*, not just the number moved.

**B1. Unhandled unit splits.** TWSE's `TWT49U` covers 除權息 but **not** unit splits.
0050 split 1:4 on 2025-06-18 (188.65 → 47.57). Since 0050 is the market-regime proxy,
its MA200 was averaging pre- and post-split prices, which pinned the whole strategy to
risk-off for months.
**Fix, and the reusable insight:** Taiwan enforces a ±10% daily price limit, so *any*
overnight move beyond that is definitionally a corporate action. Detect and
back-adjust. Found **248** such events (splits, 減資, reverse splits).

**B2. Latched drawdown trigger.** The emergency rule compared equity to the *all-time*
peak, so once 12% down the condition was true **every single day** — buy the book
Monday, dump it Tuesday, 31× a year.
**Fix:** a separate `trig_peak` that resets each time it fires, plus a cooldown.
Result went **−3.5% → +41.0%**, costs 217k → 123k.
**Reusable insight: any threshold rule on a running extreme needs a reset, or it latches.**

**B3. `trade_stats` mutated the trade log.** `b["sh"] -= take` was running on live
records during FIFO matching, zeroing every closed BUY before serialisation. Copy
before matching.

**B4. Weekly rebalance never fired live.** `step()` decided the week boundary from
`dates[di+1]` — but in a live daily run the current Friday *is* the newest row, so
`di+1` didn't exist, it returned early, and the rebalance was silently skipped and
never revisited. **Every Friday from 2026-08-17 onward was skipped.**
**Fix:** when `di+1` exists use the next session (backtest unchanged); when it doesn't,
fall back to the calendar — `d` is the week's last session iff `weekday()==4`. This can
only ever *miss* (Friday-holiday short weeks) and never fire early, so no look-ahead.
**Reusable insight: a backtest and a live run see different data shapes at the tail.
Boundary logic that reads "the next row" is a live-only landmine.**

---

## C. Design decisions, with the measurement behind them

**C1. `top_n = 6`, chosen on robustness not return.** Sam asked for 3–6 names. 3 names
scored best (+87.2%) — but shifting the pick window by one rank swung it to **−12.8%**
(a 100 pp range). At 6 names the same perturbation gives 49.6 / 23.9 / 50.4% (26 pp
range). The 3-name number was a lottery ticket. Also had to make `max_weight` derive
from `top_n` (`eff_max_w()`), otherwise a fixed 20% cap strands cash whenever the book
holds fewer than 5 names.

**C2. Odd lots (`lot_size=1`), and why the return got *worse*.** Whole lots (100)
imposed a hidden **price-cap universe filter** — any name whose one lot exceeded the
per-name budget was silently excluded, which dropped exactly the high-priced
high-momentum names. Removing it: backtest **dropped +60.7% → +34.6%**, Sharpe
1.69 → 0.92.
**It was still the right call.** The whole-lot exclusion was an *accidental helper*,
not an edge — excluding a stock purely because of its share price is an artifact. Sam's
framing: "避免單價因素排除上漲動能個股".
**Reusable insight: a constraint that improves your backtest for a reason unrelated to
your thesis is a bug you're profiting from.**

**C3. Whole-張 fill granularity, hybrid (supersedes pure odd-lot).** Sam:
"大於一張的購買就用 1000 股為單位操作". `snap_sh()` — a position larger than one board
lot rounds down to whole 1,000-share 張; anything ≤1 lot stays 零股. `lot_size` stays 1
*only* so the investability filter keeps `max_px → ∞` (preserving the C2 fix).
**Subtlety that needed a second pass:** the first implementation snapped each *order
delta*, which stacked into non-round *holdings* (2887 = 5,014 shares). The rule is about
the resulting **position**, not the order. `_fill` now drives each name to a conforming
target share count and orders the delta. Verified zero holding-level and order-level
violations.

**C4. News is display-only, deliberately.** Sam first asked to quantify news into the
score; `news_signal.py` was built (zh-TW lexicon, dated to the first trading session
≥ publish date). **Sam reversed it the same day**: historical news can't be honestly
aligned to "what was knowable then", so scoring it manufactures look-ahead and inflates
results. Correct call. News was removed from the composite; it still renders as a
manual-review panel labelled 人工複核·未計分.

**C5. Conviction sizing (position = opportunity ÷ risk).** Sam: "不必把 budget 平分…
依風險與機會決定部位". Softmax of composite score (`conv_tau=0.6`) × inverse-vol,
bounded per name to [8%, 25%] via iterative water-filling. Backtest +41.0% → +45.9%,
but trades 167 → 301 (weight drift crosses the no-trade band more often).

**C6. Weekly + monthly K-line sizing tilt.** Sam: "參考一週/一個月K線圖分析，決定持有比例".
Candle *anatomy* scored in [−1, 1] — close-in-range, body direction, green-week
consistency, upper-wick rejection. Deliberately **not** raw return, because momentum
already carries that. Applied multiplicatively to conviction **before** the clamp, so
it moves 持有比例 and never selection. Weekly +45.9% → +59.1% (Sharpe 1.34 → 1.67);
monthly stacked on top → +60.7%. Unlike news, price *is* point-in-time, so this is
honestly backtestable.

**C7. Laddered (階梯式) entry/exit.** Sam: "在信心不夠高情況下用階梯式買進賣出".
Low-conviction picks build up over up to 3 tranches; a name that drops out softly winds
down one tranche per week instead of being dumped. **Hard risk exits — stop, trailing
stop, emergency — are never laddered**, they liquidate in full. Impact: +34.6% → +42.7%,
Sharpe 0.92 → 1.32, **vol 0.378 → 0.328 (lower)**, cost 135k → 105k.
Gated by `ladder_enable`; off ⇒ byte-identical to immediate fills, which is the
regression guarantee.

**C8. Risk-adjusted momentum (`mom_risk_adj=True`), live since 2026-08-19.** Rank by
z-score(mom ÷ max(vol, 0.02)) instead of z-score(mom). Selection only — sizing already
divided by vol. Improved **every axis untuned**: +42.7% → +44.4%, Sharpe 1.32 → 1.67,
vol 27.1%, MDD −19.2%.

**C9. Two-sleeve barbell.** Covered in `01_SYSTEM_MAP.md` §2. The key measurement: the
active engine restricted to large caps returned +1.3% vs 0050 buy-and-hold +103%, so
the new NT$1M went passive rather than into more rotation.

**C10. Swap cadence — Friday only for the active sleeve.** Sam asked for twice-weekly
(每週三、週五) on 2026-09-01. Measured on the active sleeve: **+51.0% → −11.7%**, Sharpe
1.04 → −0.37, profit factor 1.58 → 0.91 (below 1 = net loser), trades 313 → 561. The
weekly momentum signal needs the hold; 2-day churn cuts winners early and doubles
fee/tax/slippage.
**Resolution:** made it a per-sleeve toggle rather than silently degrading the active
sleeve. `S.swap_window(dates, di, wed_fri)` is shared, holiday-safe, no look-ahead.
Active uses `wed_fri=False`; the **passive core uses `wed_fri=True`** (cost-insensitive,
so the regime throttle reacts ~2 days faster for free).

**C11. Stop widening, adopted 2026-09-01.** Sam: "目前勝率太低，需要持續優化".
Diagnosis first: the 44% win rate is **mostly structural and healthy** — momentum has a
fat right tail, avg win is 2× avg loss, winners are held 19 days for +17% while losers
are held 10 days for −6%. "Cut losers, run winners" is the design working.
But the STOP bucket was 81 trades (26% of all), 17% win rate, −208k total. Post-stop
analysis: **~49% of stop-outs recovered above their exit price within 20 sessions** —
the −8% stop was being triggered by ordinary TW mid/small-cap daily noise.
Widening to −12% / −15%: win **44% → 51%**, return **+51% → +67%**, Sharpe 1.04 → 1.24,
PF 1.58 → 1.74, MDD −16.6% → −17.1% (marginal). **Consistent in both year sub-splits**
(Y1 38→42%, Y2 47→53%) and the sentinel got *cleaner* (34% vs 39%).
**Reusable insight: for a momentum book the win-rate lever is stop width — reducing
false stops — not entry filters, which kill the right tail.**

---

## D. Measured and REJECTED — do not re-litigate without new evidence

**D1. Momentum ceiling (`mom_cap`).** Hypothesis was reasonable: stop-outs *do* enter
with higher raw momentum (median z 1.09 vs 0.54 for winners). But capping guts returns
**+51% → +11%**, because the high-momentum names are *also* the +157% monster winners.
Kept in the code, default `None`.

**D2. Rank hysteresis / hold-band (`hold_buffer`).** The trap, and the reason rule A2
exists. On the full window it looked excellent — buf0 +51% → buf7 +89%, Sharpe
1.04 → 1.63, with an apparently broad plateau from buf6–15. **The sub-period split
destroyed it:** in the recent-12-month window buf3/buf5 *underperform* buf0 (+42/+37 vs
+44), and buf7's look-ahead ratio crept 39% → 47.7% against a 50% alert line. The +89%
leaned entirely on 2024–25. **Not adopted.** `hold_buffer` stays 0.
(It does rescue the Wed+Fri cadence from −12% to +12% — but Wed+Fri still loses to
Fri-only, buffer or not. Twice-weekly is structurally worse.)

**D3. Volatility ceiling (`vol_ceiling`).** At 0.06 it binds and **craters** return
(+9.4%, Sharpe 0.31) because bull-year winners are high-vol. At 0.08–0.15 stacked on
top of `mom_risk_adj` it changes **nothing** — risk-adjusting momentum already keeps
the wild names out of the top 6. Kept, default `None`. Same failure mode as D1: a blunt
cut on a risk proxy is threshold-fragile.

**D4. Parameter optimisation (v0).** Sam asked to optimise on 2 years and remove the
"未最佳化" caveat. Random search, 250 combos, proper IS/OOS split with a
**pre-committed** selection rule (best in-sample Sharpe — picking by OOS just moves the
overfit up a level).
**Textbook overfit.** Best IS config: Sharpe 5.96 / +111% → **OOS Sharpe −0.88 /
−17.5%**. IS rank had ~zero OOS predictive power. The **hand-set baseline** scored IS
Sharpe 0.96 but **OOS 4.39 / +67.8% — beating every optimised candidate out of sample.**
Shipping the IS-optimal params would have taken the account from +67.8% to −17.5%.
**Decision: keep hand-set params.** The dashboard label changed from "未做最佳化" to
"已做 v0 最佳化驗證（測過、過度配適，故保留手設值）" — a stronger and more honest claim.
**Reusable insight: on short single-regime data, max-IS-metric selection is
anti-signal. A validation whose result is "don't optimise" is a real result.**
Doing it properly later needs multi-year, multi-regime data and walk-forward.

**D5. 自營商 / dealer net-buy as a scored factor (`W["dlr"]`).** Sam asked
(2026-09-14) to bring 券商 and 外資 into the strategy. 外資 was already the
second-heaviest factor (`fgn`, 0.30); the genuinely unused asset was **`dealer_net`,
which `build_db.py` has always fetched and stored and `load()` simply threw away** —
650k rows, 2024-08-01 → present, 84% non-zero. Free to test, no new data.
Wired it in as a 10-day turnover-normalised z-score (10d not 20d: proprietary desks
turn over much faster than foreign funds, so a 20d sum self-cancels).
**Every non-zero weight is worse, in both directions, on all three windows.**
Window 2025-09-15 → 2026-09-14, baseline `dlr=0`: **+83.3%, Sharpe 3.06, MDD −10.3%**.

| `W["dlr"]` | FULL ret | Sharpe | H1 ret | H2 ret |
|---|---|---|---|---|
| 0 (baseline) | **+83.3%** | **3.06** | **+23.8%** | +46.8% |
| +0.10 | +67.6% | 2.55 | +16.7% | +43.1% |
| +0.15 | +58.2% | 2.25 | +13.7% | +38.9% |
| +0.20 | +62.6% | 2.43 | +19.1% | +36.0% |
| +0.25 | +65.9% | 2.70 | +16.6% | +43.6% |
| −0.10 | +70.1% | 2.63 | +15.2% | +46.6% |
| −0.15 | +71.0% | 2.66 | +10.1% | +53.8% |

No sign preference, no plateau, H1 degrades monotonically-ish in every variant. Dealer
flow is **noise relative to the existing blend** — plausibly because 自營商 net includes
avoidance/hedging against warrants they issued, so it is not a directional view at all.
**Kept in the code at weight 0.0.** Do not re-add without a different construction
(e.g. splitting 自行買賣 from 避險, which the TWSE t86 feed does expose separately).

**D6. 外資買超「持續性」 as a separate factor (`W["fgnp"]`).** Mechanism was sound:
`fgn` is a magnitude sum and one block trade can carry it, so "what fraction of the last
20 sessions were net-buy days" is a genuinely different claim, not a re-tune. Also
rejected — and it is **the single best live demo of why rule A2 (sub-period split)
exists**, so read this one before proposing any factor:

| `W["fgnp"]` | FULL ret | Sharpe | H1 ret | H1 Sharpe | H2 ret | H2 Sharpe |
|---|---|---|---|---|---|---|
| 0 (baseline) | +83.3% | 3.06 | **+23.8%** | **+2.34** | +46.8% | +3.65 |
| +0.10 | +77.3% | 2.96 | +13.1% | +1.28 | +53.8% | +4.51 |
| +0.20 | +58.7% | 2.32 | +1.8% | +0.12 | +56.2% | +4.70 |
| +0.30 | +28.1% | 1.18 | −1.2% | −0.23 | +29.3% | +2.38 |
| **−0.15** | **+85.8%** | **+3.13** | +8.2% | +0.69 | +71.5% | +6.18 |

The −0.15 row **beats the baseline on the full window on both return and Sharpe.** On
the full window alone you would ship it. It is garbage: H1 Sharpe collapses 2.34 → 0.69
while H2 runs to 6.18, i.e. the whole gain is one concentrated stretch — and the sign
says *persistent foreign **selling** is bullish*, which has no mechanism behind it.
Full-window-only would have adopted a backwards factor. **Kept at weight 0.0.**

Both D5 and D6 were run with `exp_factor.py` (`--key dlr|fgnp --weights ...`), which
loads the DB once and reports FULL/H1/H2 for any `W` key. Use it for the next factor
proposal rather than hand-rolling a sweep.

**D7. 券商分點進出 (per-broker-branch flow) — blocked on data, not on merit.** This is
what Sam most likely meant by 券商, and it is the one idea here that was *not* rejected
on measurement, because it **cannot be measured**. Probed 2026-09-14 from the PC bridge:
- **TWSE BSR 買賣日報表** (`bsr.twse.com.tw/bshtm/bsMenu.aspx`) — reachable, but the form
  is **CAPTCHA-gated** (`CaptchaImage` present), takes **one stock at a time**
  (`TextBox_Stkno`), and serves **the current day only**. ~1,000 CAPTCHA solves per day
  for one day of coverage, and **no history at all** — so no backtest, ever, on past data.
- **TDCC 股權分散表** (`opendata.tdcc.com.tw/getOD.ashx?id=1-5`) — the clean, legitimate
  大戶籌碼 proxy: open CSV, no CAPTCHA, 2.3 MB, all listed codes, 持股分級 + 人數 + 股數.
  **But the feed serves one weekly snapshot only** (probe returned 20260911 and nothing
  else). Accumulating it forward is the only way to build history: ~6 months before
  anything is measurable, ~2 years before it spans the current backtest window.

**Sam chose both (2026-09-14) and both are now built:**

1. **Archive** — `tdcc.py fetch` writes to **`tdcc.db`, a separate file**. This matters:
   `twstock.db` is recreated from scratch every night (`build_db.py` → `mv`), so anything
   archived there would be destroyed daily. The TDCC archive is append-only and
   **irreplaceable** — a lost week cannot be backfilled from anywhere. Hooked into
   `run_daily_paper.sh` *before* `build_db.py`, and **fail-open** (`|| say WARN`): a TDCC
   outage must never stop the account advancing, because the data is display-only.
   It runs **daily** despite the data being weekly, so it would take five consecutive
   failures to actually lose a snapshot. First snapshot stored: **2026-09-11, 51,842 rows.**
2. **Display-only panel** — 集保籌碼分佈 card on the paper dashboard, between 目前持倉 and
   the allocation donut. Shows 大戶(400張+) / 千張大戶 / 散戶(10張以下) share and 股東人數,
   with week-on-week deltas. Fed from `merge_report.py` (`tdcc` + `tdcc_status` keys),
   wrapped in try/except so a TDCC problem degrades the card, not the report.

**Two traps for whoever touches this next:**
- **證券代號 is space-padded to 6 chars in the CSV** (`'2330  '`). Unstripped, every join
  against `price.code` silently returns zero rows — it fails as "no data", not as an error.
- **The week-on-week delta is the whole signal; the level is not.** 千張大戶 ≈ 85% is
  routine for a large cap (it includes foreign custodian banks) and would be remarkable
  for a small cap. The card says so in its footnote. Never rank across stocks on the level.

Rule A2 still forbids giving this a weight: one snapshot exists, and a measurement needs
~2 years of accumulation. **Revisit no earlier than 2027.** Until then it informs Sam's
eye, not the score.

---

## E. The look-ahead defence, and what it taught

Two layers, one cheap and one expensive.

**E1. Structural invariant (every fill, zero cost).** `Engine._fill()` asserts the fill
date is strictly later than the decision date. Same-bar execution is the easiest bias to
reintroduce during a refactor — one shared index between `rebalance()` and `_fill()` and
it's back — **and it cannot be detected by looking at returns.**

**E2. `sentinel.py`.** Runs a variant that *knowingly cheats* (ranks by tomorrow's
realised return) and requires the honest run to stay below 50% of its return and Sharpe.
The logic: leakage can't be judged by "is the number good", because a leaky backtest just
looks good — but it *cannot stay far away from the cheat*.
**Fault-injected to prove it fires:** injecting a next-day-price momentum leak moved the
honest run +49.6% → +675.1%, ratio 4.8% → 64.8%, exit 1. Restored and verified
byte-identical afterwards.
It gates `run_daily_paper.sh` **before** `paper.py step` — a failure means don't advance
and don't publish.

**E3. `lookahead_demo.py` findings.** Honest +49.6%; same-bar close fill **−26.9%**;
perfect intraday +315.6%; next-day ranking +1041%; perfect foresight +1,324,110%.
Two lessons: (a) **look-ahead does not always inflate** — same-bar fill was *worse* here,
but a 77 pp swing from fill timing alone shows how fragile the result is; (b) the first
version of the intraday variant was *wrong* (buying and selling at the low cancels out) —
even code written specifically to demonstrate a bias got the bias wrong.

**E4. Sentinel ratios move for innocent reasons.** Laddering raised the ratio
3.2% → 37.6% — not leakage. Laddering handicaps the *cheat* too (it can't pile into
tomorrow's known winner in one shot either), collapsing the cheat from +1030% to +126%.
Don't read a rising ratio as leakage without checking what happened to the denominator.

---

## F. The 7610 post-mortem — worth reading in full

The only realised loss of consequence, and it is instructive about what to *not*
over-correct.

**What happened.** 7610 聯友金屬-創 was picked on the 2026-08-17 decision (rank 3,
score 1.044) driven almost entirely by momentum (mom z = 0.926) after a **parabolic +69%
run in ~13 sessions** on a volatile 創新板 name. Filled 2026-08-18 at the open, 1926.92
(+4.2% gap over the prior close). Same day it reversed high 1945 → close 1740, tripping
the −8% stop. Exit staged for the next open — which gapped down again and **filled at
1635.00**. Held one trading day. **Realised −15.15%** versus −9.6% at the trigger,
NT$6,357 ≈ 0.64% of equity.

**Three root causes.** (1) Raw 60-day momentum rewards vertical, extended spikes — it
bought the top of a blow-off. (2) Odd lots admitted it: one whole lot ≈ NT$1.93M ≈ 5× the
per-name budget, so the whole-lot rule would have excluded it outright. (3) The
NT$50M turnover floor did not catch it — the parabola came with volume (NT$536M).

**What worked, and must not be over-corrected away.** Inverse-vol sizing shrank it to the
floor; laddering halved it again to a stage-1-of-2 **~4% probe**; the stop cut it
immediately. The machinery contained a bad pick *exactly as designed*.

**The execution lesson, distinct from the selection lesson.** A daily-bar stop is a
**detect-and-queue mechanism, not a hard floor.** The trigger is evaluated at the close
and fills at the next open, so the realised loss can exceed the stated percentage by
however far the name gaps overnight. The 0.1% slippage parameter models spread and
impact — it does not model a multi-hour price gap. A real broker's intraday stop-limit
would cap this in a way this engine structurally cannot simulate. **Flag it as a known
paper-vs-live divergence, not a bug to fix here.**

`mom_risk_adj` (§C8) fixed the **selection** side. It does nothing for the **execution**
side. Don't conflate them when judging whether "the fix" covers this trade.

**And: n = 1.** One trade is an anecdote. It justified a mechanism change that was then
validated full-window — it did not, by itself, justify anything.

---

## G. Known limitations, stated plainly

- ~1 year of live-equivalent decisions (~50). **Too small to separate skill from luck.**
- One regime — a bull year. Nothing here has been tested through a real drawdown.
- Not modelled: 漲跌停 lock-ups, 處置股 call-auction, trading halts, dividend tax
  (incl. 二代健保), borrow costs.
- Odd-lot intraday spreads are wider than the 0.1% slippage assumption in extremes.
- Costs assume **no broker discount** (`fee_discount=1.0`) — conservative on purpose.
- The whole system is a simulation and has never touched a real brokerage.
