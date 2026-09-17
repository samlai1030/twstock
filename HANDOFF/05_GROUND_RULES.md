# 05 — Ground rules

Sam's standing instructions for this project. These are not suggestions; several were
given as corrections after something went wrong.

---

## 1. This is a PERSONAL project. Keep it out of work tracking.

- **Do NOT file this in the work task tracker** about anything in this
  project. No `[task-notify]` pings, no T-numbers.
- **Do NOT put it in any work slide deck, status report, or org update.**
- Only **de-personalised engineering lessons** may be shared with the crew — e.g. "a
  threshold rule on a running extreme needs a reset or it latches" is fine; anything
  about Sam's positions, capital, or returns is not.
- Extra hazard: the task-tracker's delegation socket **executes** pings as tasks. A ping
  intended as FYI gets built. This already caused a duplicate once (2026-08-28). If you
  must send one, mark it "FYI ONLY, no action".

The informal "T153" label that appears in the old `README.md` title is **retired and
wrong** — the real work item T153 is the Brighton Sensor Position Model, an unrelated
optics project. Don't propagate it.

## 2. Publishing and privacy

- **The current dashboard host has no access control.** Anyone with the link reads it. This is
  acceptable today only because the dashboard shows a *simulated* account with no
  personal identifiers.
- If real holdings, real capital, or anything personally identifying ever goes on a
  dashboard, it must move to a **gated** host (an access-controlled host) — never
  that host.
- **Link format:** when sharing a dashboard link with Sam, send **just the short
  segment** — `$PAPER_URL` (see config.sh) — with no wrapper text, no markdown link, no full URL.
  He asked for this explicitly.
- Never send anything from this project into a group chat or shared space. 1:1 content
  stays 1:1.

## 3. Methodology discipline

- **Parameters were fixed before the first run and are not tuned against the same
  year.** Any proposed change needs a *mechanism* first, then a full-window
  measurement, then a **sub-period split**. See `03_DECISION_LOG.md` §D2 for why the
  sub-period split is mandatory — a change that looked like a broad +38 pp plateau was
  a time-concentrated artifact.
- The recurring review job (`twstock-review-2d`) is **observation only**. Its own prompt
  forbids optimising stop-loss / weights / top_n against the recent sample. Respect that
  boundary; do not let a two-day review turn into parameter drift.
- If you find a **code bug or data anomaly** (as opposed to a parameter question):
  **flag it and report, don't silently change the logic.**
- Never let the paper account re-implement the strategy rules. Backtest and paper share
  one `Engine` on purpose — two implementations drift silently and you won't notice.

## 4. Operational safety

- `run_daily_paper.sh` is **fail-closed** by design. Keep it that way. A stale-but-correct
  account beats one advanced on partial data. Don't "helpfully" add a fallback that lets
  it proceed on a short fetch.
- The sentinel gates the account advance. **Never move it after `paper.py step`, and
  never make it non-blocking.**
- Don't relax the `_fill()` fill-date assertion. It is the cheapest guard in the system
  and it catches the bias you cannot see in the returns.
- `trash` over `rm`. Recoverable beats gone.
- Ask before anything that leaves the machine.

## 5. Communication

- Sam writes 繁體中文 or English and switches freely. **Follow his lead per message.**
- He is an optical engineer, not a finance person — but he is rigorous and he will spot
  a number that has been dressed up. Report results plainly, including when they're bad.
  The +51% → −11.7% cadence result was reported as-is and that was the right call.
- Don't quote flattering statistics from tiny samples as if they were meaningful. A
  Sharpe of 4.1 over 19 days is noise; say so.
- He prefers short. Lead with the answer.
