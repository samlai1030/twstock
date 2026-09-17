# START HERE — 台股 paper-trading system handoff

**Written by:** the maintaining agent — 2026-09-14
**For:** the next agent who takes this project over / moves the dashboard to another platform
**Owner:** Sam Lai (賴聖佩). Timezone Asia/Taipei. Writes 繁體中文 or English — follow his lead per message.

---

## 60-second orientation

The owner runs a **simulated (paper) Taiwan-stock account**, live since 2026-08-18. It is driven by a backtested momentum/chip-flow strategy that advances
itself every weekday evening via cron, and publishes a self-contained HTML dashboard.

- **This is a personal project, not work.** See `05_GROUND_RULES.md` — it must NOT be
  reported to the work task tracker, and must NOT appear in any work slide deck.
- **It is a simulation.** No real money, no broker connection. Nothing here is
  investment advice, and nothing here should be pointed at a real brokerage without
  Sam explicitly asking.
- **The hard-won value is in the decision log, not the code.** The code is ~1,500 lines
  of readable Python. What took a month to learn is *why each parameter is the value it
  is, and which "obvious improvements" were measured and rejected*. That's
  `03_DECISION_LOG.md`. Read it before you change a single number.

## Read in this order

| # | File | What it gives you |
|---|---|---|
| 0 | `00_START_HERE.md` | this page |
| 1 | `01_SYSTEM_MAP.md` | architecture, data flow, file-by-file inventory, what's essential vs disposable |
| 2 | `02_LIVE_STATE.md` | frozen snapshot of the account, params, positions, DB coverage. **Local only — not in the public repo, it holds real position data.** |
| 3 | `03_DECISION_LOG.md` | **the expensive part** — every parameter's justification, every rejected idea, every bug that changed the answer |
| 4 | `04_MIGRATION_PLAN.md` | platform dependencies, what breaks on a move, target-by-target checklist, open questions for Sam |
| 5 | `05_GROUND_RULES.md` | Sam's standing rules. Non-negotiable. Read before publishing anything. |
| — | `manifest.json` | the same snapshot, machine-readable — account, params, DB coverage, file lists |
| — | `state_snapshot_2026-09-11/` | verbatim copies of the live state files, so a migration can be proven lossless |

Also in the project root (one level up): **`README.md`** — the original technical
write-up. Still accurate on data sourcing, strategy logic, and the three
methodology landmines. It is **stale from 2026-08-19 onward** (it predates the
two-sleeve split, the stop widening, and the whole-lot fill rule). Where README and
`03_DECISION_LOG.md` disagree, the decision log wins.

## What the next agent is being asked to do

Sam (2026-09-14): *"I want move my stock dashboard to other platform."*

**The target platform was not specified.** `04_MIGRATION_PLAN.md` breaks down what a
move actually involves and lists the candidate targets with their tradeoffs. **Ask Sam
which target before you build anything** — the answer changes roughly half the work.

A sharp thing to know going in: the dashboard is a **single self-contained HTML file**
with no server, no build step, and no external asset references. Moving *the dashboard*
is genuinely easy. The part that is not easy is moving **the daily pipeline that feeds
it** — that depends on a Windows-PC bridge that only exists on Sam's setup. Don't
conflate the two. See `04_MIGRATION_PLAN.md` §2.

## Current health (as of the last run, 2026-09-11 05:01 server time)

- Daily cron: **running clean**, no ABORT in the log.
- Look-ahead sentinel: **CLEAN** (last weekly regression 2026-09-11, ratio 38.0% vs
  the 50% alert line).
- **One known data gap:** the margin (融資融券) feed has been stuck at 2026-08-18 for
  ~4 weeks. The −0.10 margin signal is therefore going neutral on every recent
  decision. Flagged to Sam repeatedly, not yet fixed. See `02_LIVE_STATE.md` §4.
