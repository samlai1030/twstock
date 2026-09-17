# 01 — System map

Project root: `<project-root>/`
(~339 MB total, of which ~325 MB is the SQLite DB + raw archives.)

---

## 1. Data flow, end to end

```
  Sam's Windows PC                  devserver (this machine)
  ────────────────                  ────────────────────────
  TWSE open endpoints
    MI_INDEX   (OHLCV)
    T86        (三大法人籌碼)   ──┐
    MI_MARGN   (融資融券)        │  pc-operation bridge
    TWT49U     (除權息)          │  (pc.py exec / download)
  cnyes + Yahoo RSS (news)     ──┘
         │                              │
         │  zip → download              ▼
         └────────────────────────►  raw/*.json.gz
                                        │
                                   build_db.py
                                        ▼
                                   twstock.db  (SQLite)
                                        │
                                   sentinel.py  ◄── GATE: fail ⇒ stop, don't advance
                                        │
                          ┌─────────────┴─────────────┐
                     paper.py step            merge_report.py step-core
                   (ACTIVE sleeve)               (CORE sleeve)
                          └─────────────┬─────────────┘
                                merge_report.py report
                                        ▼
                                paper_result.json
                                        │
                                make_dashboard.py
                                        ▼
                              paper_dashboard.html  (single file, self-contained)
                                        │
                          publish() hook  (configured in config.sh)
```

**Why the PC bridge exists:** the devserver has **no external network egress** —
fwdproxy is blocked and WebFetch domains are blocked. Sam's Windows PC does have
internet. So every external fetch runs *on the PC* via the `pc-operation` skill
(`.claude/skills/pc-operation/pc.py`), writes to `C:\myclaw_tw\raw\`, gets zipped,
and is pulled back. **This is the single biggest platform dependency in the whole
system.** See `04_MIGRATION_PLAN.md` §2.

---

## 2. The two sleeves

The NT$2M account is a **barbell**, deliberately:

| Sleeve | Capital | What it does | State file |
|---|---|---|---|
| **ACTIVE** | NT$1M (opened 2026-08-18) | 中小型主動 α — momentum + chip-flow rotation, 6 names, weekly swap | `paper_state.json` |
| **CORE** | NT$1M (injected 2026-08-31) | 大型權值被動核心 — buy-and-hold 0050 ETF + regime throttle | `paper_state_core.json` |

Why not run the active engine on large caps too: it was measured. Restricting the
rotation engine to the top-50 large caps returned **+1.3%** (Sharpe ~0, 172 trades)
versus simply holding 0050 at **+103%** (Sharpe 3.75). So the second NT$1M is passive
on purpose. Full reasoning in `03_DECISION_LOG.md`.

`merge_report.py` combines them with **TWR contribution accounting**, so the
NT$1M deposit on 2026-08-31 is not counted as a return (the daily return is
neutralised on the flow day and the benchmark gets the same cash-flow timing).

---

## 3. File inventory

### Core engine — do not lose these

| File | Lines/size | Role |
|---|---|---|
| `strategy.py` | 53 KB | **The heart.** Signals, universe, scoring, sizing, laddering, rebalance, stops, the `Engine` class, and the global param dict `P`. Backtest *and* paper trading share this one implementation — that is deliberate (see decision log). |
| `paper.py` | 12 KB | Paper-account driver for the ACTIVE sleeve: `init` / `step` / `orders` / `report`. Date-keyed state. |
| `core_sleeve.py` | 7.5 KB | `CoreSleeve` class — passive 0050 with regime throttle, mirrors the main Engine's cost model and lot snapping exactly. |
| `merge_report.py` | 12 KB | Two-sleeve merge: `init-core` / `step-core` / `report`. TWR contribution accounting. |
| `report.py` | 7.5 KB | Backtest runner + risk metrics (Sharpe/Sortino/MDD/Calmar), `trade_stats`, benchmark comparison. |
| `make_dashboard.py` | 45 KB | `*_result.json` → single self-contained HTML. All CSS/JS inlined, no external assets. |
| `build_db.py` | 8 KB | raw JSON.gz → SQLite (`price` / `chip` / `margin` / `exright`). Handles 除權息 back-adjustment and the ±10% corporate-action detector. |
| `sentinel.py` | 4 KB | Look-ahead guard. Runs a deliberately-cheating variant and requires the honest run to stay <50% of it. **Note: self-executes on import** (`sys.exit(main())` at module level) — never `import sentinel` from another script. |
| `kline_signal.py` | 4.8 KB | Weekly + monthly candle-anatomy scoring, used as a *sizing* tilt only. |
| `news_signal.py` | 3.9 KB | zh-TW finance sentiment lexicon. **Display only — deliberately NOT in the decision score.** |
| `tdcc.py` | 8 KB | 集保股權分散表 archiver + 籌碼集中度 metrics. **Display only.** Fetches via the PC bridge, writes `tdcc.db`. See decision log D7. |
| `exp_factor.py` | 2 KB | Factor-sweep harness: `--key <W key> --weights ...` loads the DB once and reports FULL/H1/H2. Use this for any new factor proposal instead of hand-rolling a sweep. |

### Fetchers (run on the Windows PC, not here)

`fetch_pc.py` (main 3-feed fetcher, threaded, resumable) · `fetch_extra_pc.py`
(除權息) · `fetch_news_pc.py` (RSS). Copies live at `C:\myclaw_tw\` on the PC.

### Orchestration

| File | Role |
|---|---|
| `run_daily_paper.sh` | **The production cron.** Fail-closed: PC bridge down or short data ⇒ exit without touching state or republishing. Read this file top-to-bottom, it documents the whole daily sequence. |
| `run_weekly.sh` | Full backtest refresh + backtest-dashboard publish. **Manual, not scheduled.** |
| `push_to_github.sh` | Sync the repo to GitHub. Not a plain `git push` — this host cannot resolve github.com, so it bundles, chunks over the PC bridge, and pushes from the PC. Read its header before touching it. |
| `config.example.sh` | Template for `config.sh` (gitignored): host paths + the `publish()` hook. All site-specific settings live there, nothing strategy-related. |

### State (live — back these up before any move)

`paper_state.json` (64 KB, active sleeve) · `paper_state_core.json` (1.8 KB) ·
`paper_result.json` (68 KB, merged report the dashboard reads) ·
`paper_orders.json` (next session's staged orders) · `sentinel_last.json` ·
`.sentinel_hash` · `paper.log` (32 KB rolling log).

### Data

| File | Size | Note |
|---|---|---|
| `twstock.db` | 175 MB | SQLite. **Rebuildable from `raw/`** — don't bother copying it, rebuild instead. Note it is recreated from scratch nightly, so never archive anything into it. |
| `tdcc.db` | grows ~2 MB/week | 集保 weekly snapshots. **MUST be carried on any migration — it is irreplaceable.** The TDCC feed serves only the newest week with no history endpoint, so a lost snapshot is lost permanently. Started 2026-09-11. |
| `raw/` | 78 MB | Raw TWSE JSON.gz, one file per feed per day. **This is the real asset** — it is the only copy of the history, since TWSE endpoints throttle bulk backfill. |
| `raw_all.zip` / `raw_partial.zip` | 73 / 12 MB | Older archive snapshots of `raw/`. Redundant with `raw/`; safe to drop. |
| `news.json.gz` | 43 KB | Latest news pull. |

### Disposable — do not carry these to a new platform

`__pycache__/` · `strategy.py.bak` · `paper_state.bak.json` ·
`paper_state.prev.json` · `paper_state.reset0831.json` · `paper_result.bak.json` ·
`dashboard.html` / `tw_dashboard.html` (old generated output) ·
`manual_run.out` (empty) · `raw_all.zip` / `raw_partial.zip` ·
`result_lot100.json` / `topn_sweep.json` / `diagnostics.json` /
`lookahead_demo.json` / `optimized_params.json` (one-off experiment records —
their *conclusions* are all captured in `03_DECISION_LOG.md`).

Keep `lookahead_demo.py`, `optimize.py`, `compare_guards.py`, `diagnose.py`,
`add_context.py` — they are the reusable experiment drivers, cheap to carry.

---

## 4. Scheduling (current)

**System crontab:**
```
0 5 * * 1-5   projects/twstock/run_daily_paper.sh
```
05:00 server time = **20:00 Taipei**, Mon–Fri. That slot is chosen deliberately:
after the 13:30 TWSE close *and* after the margin balances publish in the evening.
Running earlier silently neutralises the −0.10 margin signal.

**Scheduled job** (held in the agent runtime's own job store):
`twstock-review-2d` — interval 172800 s (2 days). Reads the state files and posts a
Chinese review to Sam's chat, ending with the bare dashboard short link. It is
**observation only** — its prompt explicitly forbids tuning parameters against the
recent sample. If you move platforms, this job has to be recreated on whatever the
new scheduler is.

---

## 5. Published artifacts

| What | URL | Refreshed by |
|---|---|---|
| Paper dashboard (live account) | `$PAPER_URL` (see config.sh) | `run_daily_paper.sh`, daily, **in place** |
| Backtest dashboard | `$BT_URL` (see config.sh) | `run_weekly.sh`, manual, **in place** |

Both are updated with `the `publish` hook from config.sh`, which
creates a **new revision at the same URL**. (The reference host distinguishes *update* — new revision, same URL — from
*upload*, which mints a new link; the daily run used to do the latter by mistake.
Whatever host you move to, make sure the publish step is in-place.)

**Privacy constraint:** the current dashboard host has **no access control** — anyone with the link
can read it. This is acceptable *only* because the dashboard shows a simulated
account with no personal identifiers. See `05_GROUND_RULES.md`.
