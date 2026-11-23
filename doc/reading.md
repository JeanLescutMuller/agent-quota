# Reading the tracker's data

How agent-quota reads the quota and the $ from the tracker (agent-tracker), read-only: which files, which tables and columns, how fresh they are, and the traps found in the real rows. Code: `src/agent_quota/reading.py` (files), `src/agent_quota/forecast.py` (cleaning, burn rate). The tracker's own rules: `/Users/jeanlescut/dev/agents/agent-tracker/FOR_READERS.md`. Verified against `/Users/jeanlescut/opt/agent-tracker/data/claude/` on 2026-11-16.

## 1. Files

All under `$AGENT_QUOTA_TRACKER` (default `~/opt/agent-tracker/data/claude`; `src/agent_quota/paths.py`).

| File | What agent-quota reads | Function |
|---|---|---|
| `quota_latest.<name>.json` | the account's freshest reading (one file per account): `ts`, `source` (`statusline` or `poller`), `machine`, `five_hour` / `seven_day` = `{used_percentage, resets_at}` or `null` | `read_meters(now)` |
| `account_quotas.db`, table `account_quotas` | every reading, both machines: `ts`, `written_ts`, `source` (`claude_statusline`, `claude_api`), `machine`, `five_hour_pct`, `five_hour_resets_ts`, `seven_day_pct`, `seven_day_resets_ts` | `read_meters(now)` (newest row, a second source), `meter_history(since_ts, until_ts=None)` |
| `sessions_usages.db`, table `telemetry` | one row per API request event of this machine: `ts`, `event` (`api_request`…), `session_id`, `request_id`, `cost_usd` | `session_usd(since_ts, until_ts)` |

Not read: the view `latest` (it applies the reset rule with SQLite's own clock, which a test or a replay must not use: `read_meters` runs the same query on the raw columns with its `now`), the view `telemetry_requests` (see §3), `slots`, `session_snapshots`, `intermediary.db` (not for readers).

## 2. How the files are opened

| Rule (FOR_READERS) | Here |
|---|---|
| never write | `PRAGMA query_only = ON`; the URI `file:…?mode=rw` never creates a missing database (a plain `connect` would); `quota_latest.<name>.json` is only read |
| never `mode=ro` (macOS refuses it intermittently on these WAL files) | `mode=rw` + `query_only` |
| busy timeout | 10 s (`timeout=10`, `PRAGMA busy_timeout = 10000`) |
| rule 8: a passed reset reads 0 % | applied with the caller's `now` in `read_meters`, and per row (at the row's `ts`) in `meter_history`: `pct` 0, `resets_at` None |
| rule 16: a meter may be `null` in `quota_latest.<name>.json` | read as 0 %, reset unknown (no window open) |
| a quota % is account-wide | no function gives a session a %; `session_usd` gives $ only |

A missing or broken file never raises from `read_meters`: it returns both meters with `pct` None, `stale` True and `error` set, so the shared check gives `nobody` (R41). `session_usd` returns `{}` when `sessions_usages.db` is absent; `meter_history` raises `FileNotFoundError`.

## 3. Freshness and time keys

| Question | Answer | Verified |
|---|---|---|
| Is a reading fresh? | `stale` when `now − ts > READING_MAX_AGE_S` (600 s). Both meters share one reading, so both are stale together | — |
| Which reading is "now"? | the larger `ts` of `quota_latest.<name>.json` and the newest `account_quotas` row with `ts ≤ now` (a replay never sees the future); on a tie, the JSON | 2026-11-16: both within 10 s of each other |
| How often is there a reading? | the Mac's poller (`claude_api`) about every 2 min while Claude is used, the status line on each new value; the VM's poller less often | last 7 days: 2,541 Mac poller rows, 297 VM poller rows, 5,625 status line rows |
| History keyed by `ts` or `written_ts`? | by `ts` (the tracker's rule 10). `written_ts` was tried first and rejected: a status line re-sent a week at 80 % on Sunday 2026-11-15 14:00 whose `ts` was Thursday 10:39, before the week's reset | 2026-11-16 |
| The price of keying by `ts` | a status line row's `ts` is its session's last main-thread response: a session waiting on its subagents writes 55 %, 56 %… 59 % all with one `ts`, up to 15 min before they were true (`ts` 1794832592, written 1794832641 → 1794833481). The poller's rows, written at the same minutes, match the `written_ts` within seconds. Effect: a recent slope a little low at the edge of the 30 min; the × 1.5 covers it | 2026-11-16 |
| A replay at time t | `meter_history(since, until_ts=t)` keeps only rows with `ts ≤ t` and `written_ts ≤ t`: what was known at t | — |
| `session_usd` dedup | Claude Code re-sends batches: one row per `request_id` (the lowest `rowid`), as the view `telemetry_requests` does, but restricted to the time range first: 0.007 s instead of 0.95 s for the view | 2026-11-16 |
| A session's subagents | their requests carry the parent's `session_id` (`query_source` `agent:builtin:general-purpose`…): counted in the session | 2026-11-16 |
| Speed on the real files | `meter_history(now − 7 days)` 8,512 rows in 0.07 s; `read_meters` 0.001 s; the shared check 0.015 s | 2026-11-16 |

## 4. Traps in the real rows, and what the cleaning does

`forecast._steps` turns a history into the current window's (or week's) running maximum. Each rule below comes from a real case.

| Trap | Example (UTC) | Rule |
|---|---|---|
| The same reset reads ±1 s across sources | `five_hour_resets_ts` 1794835199 (poller) vs 1794835200 (status line) for one window | same window when the resets differ by ≤ `RESET_TOLERANCE_S` (120 s) |
| A stale low re-sent with a fresh `ts` | Thu 2026-11-12 23:15:26, session `0615d2de`: week 59 % between two rows at 93 % | dropped: within one window only the running maximum counts |
| Two machines disagree | the VM's poller at 56 %, then the Mac's status line at 49 % | dropped the same way |
| **The week reset early, its reset time unchanged** | Fri 2026-11-13 17:47:10: the poller reads week 95 % → 0 % (window 3 % → 0 %, a new window), `seven_day_resets_ts` still Mon 19:00. Contradicts "within one window the % never decreases" (FOR_READERS rule 10) for the week | a reset = the poller (`claude_api`) reading more than `RESET_FALL_PCT` (5) points below the poller's own running maximum; the meter re-opened at that reading. A status line is never trusted for a fall (its `ts` can be early) |
| A stale high from before a reset | Fri 2026-11-13 17:47:13, status line: week 95 % with `ts` 17:33:36, written 3 s after the reset | keyed by its `ts`, it falls before the reset: harmless |
| `quota_latest.<name>.json`'s `source` names differ from the table's | `poller` / `statusline` in the JSON; `claude_api` / `claude_statusline` in `account_quotas` | `Meters.source` keeps whichever was read; the cleaning uses the table's names |

## 4b. Several Claude accounts (2026-11-19)

agent-tracker's rule 19 (`FOR_READERS.md`): `account_quotas.account` is the organization uuid (NULL = before 2026-11-19 = the account named a), the table `accounts` maps names to uuids, an account's file is `quota_latest.<name>.json`. `reading.py` reads **the session's own account**, named by `$CLAUDE_ACCOUNT` (set by my-setup's `claude-account`; the name selects the file `quota_latest.<name>.json` and the rows with that account's uuid). Unset, or a name that is not `[a-z0-9_-]+` (a session started outside the wrapper): the account with the most room left among the `quota_latest.<name>.json` files (room = 100 - max(5h %, 7d %), rule 8 at `now`; a tie: the first name; no file: `a`). A tracker from before 2026-11-19 (no `account` column) answers for the account named a only. Without this, a session on account b would read the newest row of any account and be throttled (or not) by a's quota. `forecast` and the protector's state (`state.py`) are unchanged: each hook call reads its own account's history, so the forecast of account b has little history until it is used (`meter_history` returns what exists).

## 5. Not solved in v1

- `read_meters` returns the freshest single reading: a stale low with a fresh `ts` (the 59 % above) can be the "now" reading for a few seconds, until the next render. The burn rate is not affected (it uses the running maximum).
- A stretch with no reading (FOR_READERS rule 9) is unknown: the slope then spans only the readings seen, and a meter older than 600 s is stale, so nobody acts.
