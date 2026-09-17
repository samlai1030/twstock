# 04 — Migration plan

Sam's ask (2026-09-14): *"I want move my stock dashboard to other platform."*

**The target platform was not specified.** Ask before building. This file exists so
that conversation takes five minutes instead of an hour.

---

## 1. First, separate the two things being moved

People say "move the dashboard" and mean one of two very different jobs:

| | Job A — move the **dashboard** | Job B — move the **pipeline** |
|---|---|---|
| What moves | the published HTML artifact + its URL | the daily fetch → DB → engine → render chain |
| Difficulty | **easy** | **hard** |
| Why | `paper_dashboard.html` is a single self-contained file. No server, no build step, no external assets, no API calls at view time. Any static host works. | It depends on a Windows-PC network bridge, a 175 MB SQLite DB, cron, and the `meta` CLI. |
| Blocker | none, really | external network egress (see §2) |

**Confirm with Sam which one he wants.** If he only wants the dashboard viewable
somewhere else — that is close to a copy-and-upload. If he wants the whole system to
*live* somewhere else, that is a real port and §2 is the crux of it.

## 2. The hard dependency: external network egress

The devserver has **no outbound internet** — fwdproxy blocked, WebFetch domains
blocked. Every TWSE and RSS fetch runs on **Sam's Windows PC** through the
`pc-operation` bridge (`pc.py exec` / `pc.py download`), writing to `C:\myclaw_tw\`.

This means:

- **Any target platform that has normal internet access makes the bridge unnecessary** —
  the fetchers become direct `urllib` calls and the system gets *simpler*. This is the
  single biggest argument for moving off the devserver.
- **Any target that also lacks egress** inherits the bridge, and the bridge only works
  where the `pc-operation` skill and Sam's PC are both reachable. That is effectively
  "this machine only".
- The fetch logic itself is portable — it's plain `urllib` + gzip inside the
  `pc.py exec` payload in `run_daily_paper.sh`, plus `fetch_pc.py` / `fetch_news_pc.py`.
  Lifting it out of the bridge is maybe an hour's work.

## 3. Candidate targets

Ranked by how much they actually solve. Sam should pick; these are the tradeoffs.

**(a) Keep the pipeline where it is, publish the dashboard elsewhere.**
Smallest change. Swap the `publish()` hook in `config.sh`
for whatever the new host's upload command is. Everything else untouched.
Good if the complaint is purely "I don't like the current host" or "I want it gated".
*Cost: ~30 minutes.*

**(b) Move to Sam's Windows PC entirely.**
The PC already has the data, the internet, and a copy of the fetchers. This *removes*
the bridge instead of porting it. Needs Python + SQLite on the PC, Task Scheduler
instead of cron, and a new publish target. Biggest simplification available.
*Cost: half a day. Risk: the PC has to be on at 20:00 every weekday.*

**(c) A cloud VM / container with real egress.**
Cleanest long-term: cron works, egress works, no bridge, always on. Costs money and
puts Sam's personal project on infrastructure he has to maintain.
*Cost: a day, plus ongoing.*

**(d) GitHub Actions (or equivalent CI) + GitHub Pages / static host.**
Scheduled workflow does the fetch and render; the HTML lands on a static host. Free,
always on, no machine to babysit. Constraint: the 175 MB DB doesn't belong in git —
it would need to be rebuilt from `raw/` each run, or cached as an artifact, or the
`raw/` archive stored somewhere with an object store.
*Cost: a day. Elegant if the DB-size problem is solved cleanly.*

**Not recommended: Google Sheets / Looker Studio.** The dashboard renders custom
candlestick SVGs, a ladder-progress column, and a live parameter card read from the
engine. Re-expressing that in a BI tool loses most of it.

## 4. What must survive the move, whatever the target

Non-negotiable, in rough priority order:

1. **`raw/`** (78 MB). The only copy of the history. TWSE throttles bulk backfill, so
   if this is lost the DB cannot be reconstructed. **Back this up before touching
   anything.**
2. **State files** — `paper_state.json`, `paper_state_core.json`, `paper_orders.json`.
   The account's identity. Lose these and the account resets to zero.
3. **The engine** — `strategy.py`, `paper.py`, `core_sleeve.py`, `merge_report.py`,
   `report.py`, `make_dashboard.py`, `build_db.py`, `kline_signal.py`, `news_signal.py`.
4. **The guards** — `sentinel.py` and the `_fill()` date assertion. If a migration drops
   the sentinel from the daily chain, the system loses its only leakage alarm.
   **Verify the sentinel still gates `step` after the move, and fault-inject once to
   confirm it still fires.**
5. **This HANDOFF folder.**
6. `twstock.db` — *don't copy it*, rebuild from `raw/` on the new host. It's 175 MB and
   `build_db.py` regenerates it deterministically.

## 5. Migration checklist

```
[ ] Ask Sam which target platform, and whether Job A or Job B (§1).
[ ] Back up raw/ + all *state*.json to somewhere outside this directory. FIRST.
[ ] Record the current numbers so you can prove the move was lossless:
      equity · TWR · position count · DB row counts
      (see the local 02_LIVE_STATE.md for the actual figures)
[ ] Stand up Python 3 + sqlite3 on the target. No third-party deps —
      the engine is stdlib-only by design. Keep it that way.
[ ] Rebuild the DB:  python3 build_db.py raw twstock.db
      Verify: price row count matches, max(date) matches.
[ ] Restore state files. Run `python3 paper.py report` and diff the
      output against the recorded numbers. It must match exactly.
[ ] Re-point the data fetch:
      - target HAS egress  -> lift the urllib payload out of run_daily_paper.sh
                              into a plain script; drop the pc.py calls
      - target LACKS egress -> keep the pc-operation bridge; confirm pc.py health
[ ] Re-point the publish step (the `publish()` hook in `config.sh`).
[ ] Recreate the schedule. 20:00 Taipei, Mon-Fri, AFTER the margin publication.
      Do not move this earlier — it silently neutralises the margin signal.
[ ] Recreate the `twstock-review-2d` review job on the new scheduler.
[ ] Run the sentinel once with --force. Must print CLEAN.
[ ] Fault-inject the sentinel once to confirm the alarm still fires, then restore
      and verify byte-identical. (A guard that has never fired is decoration.)
[ ] Run one full daily cycle end to end and diff the dashboard against the old one.
[ ] Only then decommission the old cron entry.
```

## 6. Fix this during the migration, not after

The **margin feed has been stuck since 2026-08-18** (`02_LIVE_STATE.md` §4). It fails
*silently* — the log message is indistinguishable from a normal same-day delay. A
migration is exactly the moment you'd otherwise carry the breakage across and then
attribute it to the move. Diagnose the `MI_MARGN` fetch before or during, and add a
staleness check: if `max(margin.date)` is more than ~3 sessions behind
`max(price.date)`, say so loudly in the log instead of shrugging.

## 7. Open questions for Sam

1. **Which platform**, and is this Job A or Job B?
2. **What's driving the move?** Cost, access control, the GChat→Slack migration,
   devserver reliability, or just wanting it off work infrastructure? The reason
   narrows the target list fast.
3. **Does it need access control?** The current host is public-to-anyone-with-the-link. That
   has been fine so far because the account is simulated and carries no personal
   identifiers — but if he ever wants real holdings on it, the host must be gated.
4. **Should the review job move too**, or stay on the current scheduler?
5. **Is the paper account continuing**, or is this a good moment to reset the book?
   (He has reset it before — "歸零再來一次", 2026-08-31.)
