# Design — the protector, version 1

What we build first, how the parts fit, and why. Serves [`REQUIREMENTS.md`](REQUIREMENTS.md) (R30–R47) and the shared R1–R5 ([`../REQUIREMENTS.md`](../REQUIREMENTS.md)). Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary. Written 2026-11-16 by Claude on Jean's go-ahead ("go with your defaults… move as fast and as far as you can with your own assumptions"): every choice here is **[assumed]** until Jean reviews it, unless marked **[verified]**.

| | |
|---|---|
| Command | `agent-quota` (`bin/agent-quota`): `status`, `decide`, `go-on`, `resume-now`, `mode`, `hook` |
| Reads | the tracker (read-only, its `FOR_READERS.md` rules): `quota_latest.json`, the quota history (`account_quotas.db`), per-session $ (`telemetry` in `sessions_usages.db`); the hook's own registry of sessions |
| Writes | `$AGENT_QUOTA_HOME` (default `~/opt/agent-quota/state/`): `decisions.json` (now), `decisions.jsonl` (history, R47), `sessions/<session_id>.json`, `overrides.json`, `mode` |
| Acts | yes, when `mode` = `on`: holds tool calls of the sessions it decided to freeze. Default `observe`: decides and logs, never holds |
| Consumed by | Jean (`agent-quota status`, the decision log); later the maximizer (`agent-quota state --json`, the shared check) |

```
every tool call of every Claude Code session (PreToolUse hook, all tools, subagents too)
   │
   ▼
agent-quota hook ── records the session (sessions/<id>.json: label, cwd, last call, agent ids)
   │                decisions.json older than 60 s? → recompute it (one process at a time, file lock)
   │
   ├─ decision allow (or mode observe/off) ─────────────► exit 0 at once: the call runs
   └─ decision freeze (mode on) ─► notify Jean (pane) ─► wait, re-reading decisions.json every 30 s
                                                         until allow, an override, or 6 h ─► exit 0
agent-quota decide (the recompute):
   reading  : meters (window, week) + history + $ per session over the last 30 min
   forecast : burn rate per meter → projected time at 100 % → lockout minutes
   state    : per meter: lockout ahead / normal / spare quota → who may act (R1)
   protector: per session: allow / freeze, with the reason
```

## 1. Modules and their contracts

Python 3, standard library only (as the legacy maximizer and the tracker). Package `src/agent_quota/`.

| Module | Gives | Notes |
|---|---|---|
| `paths.py` | `home()`, `tracker_dir()` | `$AGENT_QUOTA_HOME`, `$AGENT_QUOTA_TRACKER` (default `~/opt/agent-tracker/data/claude`) override them: every test runs on its own folders |
| `reading.py` | `read_meters(now) → Meters`; `meter_history(since_ts) → [Reading]`; `session_usd(since_ts, until_ts) → {session_id: usd}` | a `Meter` has `pct`, `resets_at`, `reading_ts`; a passed reset reads 0 % (tracker rule 8); a reading older than `READING_MAX_AGE_S` is **stale** |
| `forecast.py` | `burn_rate(history, meter_name, now) → % per minute`; `project(meter, rate, now) → Projection(full_at, lockout_min)` | the legacy maximizer's measured rule: max(slope over the last 30 min, average since the window opened) × 1.5 **[verified best on Pro data, legacy lab]**; `full_at` None when 100 % is not reached before the reset |
| `state.py` | `meter_state(...)`; `week_spare_pct(...)`; `who_acts(window_state, week_state)` | the shared check (R1): see §3 |
| `protector.py` | `decide(now, meters, projections, sessions, usd_by_session, overrides, config) → {session_id: Decision}` | see §4; pure: no file access, so it is tested with plain values |
| `store.py` | read/write `decisions.json`, append `decisions.jsonl`, sessions registry, overrides, mode; the recompute lock | every whole-file write = temp file + rename |
| `hook.py` | the PreToolUse hook | never raises: any error → log it, exit 0 (the call runs) |
| `cli.py` | the commands | |

## 2. Starting values

| Parameter | Value | Owner | From |
|---|---|---|---|
| `RESERVE_WINDOW_PCT`, `RESERVE_WEEK_PCT` | 5, 5 | §4 | Jean, 2026-11-16 |
| `LOCKOUT_VS_DELAY` | 10 | §4 | Jean, 2026-11-16 |
| `READING_MAX_AGE_S` | 600 | reading | the maximizer's design §9 |
| `RECENT_MIN`, `RATE_FACTOR` | 30, 1.5 | forecast | legacy lab, measured best |
| `ACTIVE_MIN` | 30 | §4 | legacy lab: "active in the last 30 min" is the strongest signal |
| `P_NEED_ACTIVE`, `P_NEED_IDLE` | 0.52, 0.13 | §4 | legacy lab: chance Jean uses > 25 % of a window within 5 h, active vs not **[measured on Pro]** |
| `BIG_JOB_PCT_PER_HOUR` | 10 | §4 | **[assumed]**: a session that alone would use 10 % of a window per hour |
| `DECISION_MAX_AGE_S` | 60 | hook | **[assumed]** |
| `HOLD_POLL_S`, hook `timeout` | 30, 21600 | hook | the 5 h 05 min test passed **[verified 2026-11-11]**; 6 h covers any window |
| `RESUME_STAGGER_MIN` | 5 | §4 | **[assumed]**: R44 |
| `WINDOW_SHARE_OF_WEEK_PCT` | 13.2 | §3 | one full window = B ÷ B_week = $194 ÷ $1,469 **[measured, Max 5x, 2026-10-12]** |

## 3. The shared check (R1, R2, R4, R5)

```text
for each meter (window, week):
    rate      = burn_rate(meter)
    full_at   = now + (100 − pct) / rate            (None if rate = 0 or full_at ≥ resets_at)
    lockout   = resets_at − full_at                  (minutes; 0 if full_at is None)
    lockout ahead ⇔ full_at is not None             (the meter will reach 100 % before its reset)
week only:
    windows_left = hours to the week's reset ÷ 5
    spare_pct    = (100 − week_pct) − windows_left × WINDOW_SHARE_OF_WEEK_PCT
    spare quota  ⇔ spare_pct > 0 and not lockout ahead
who acts:  lockout ahead on either meter → protector · else week spare quota → maximizer · else nobody
```

The window never yields spare quota (R4): quota left in a window is not lost while the week is the limit.

## 4. The protector's decision (R30–R44)

```text
candidates = sessions seen in the last 10 min, minus:
    label urgent, or an override "go on" for this window              (R40, R46)
    interactive sessions not labelled big                             (R32: never frozen; v1 warns only)
    sessions below BIG_JOB_PCT_PER_HOUR and not labelled big/maximizer (small work)
for each meter with lockout ahead:
    p_need  = P_NEED_ACTIVE if an interactive session was used in the last ACTIVE_MIN else P_NEED_IDLE   (R33)
    harm    = lockout_min × p_need × LOCKOUT_VS_DELAY        # the cost of doing nothing
    cost    = minutes from now to full_at                     # how much work a freeze takes from the jobs:
                                                              # after full_at they would be stuck anyway (R37)
    act now ⇔ harm > cost and pct + rate × 5 min ≥ 100 − reserve   (the reserve is about to be touched)
    if act: freeze candidates in order (label maximizer first, then big, then the highest $ in the last
            30 min) until the remaining rate, without them, no longer reaches 100 − reserve before the reset (R39)
release (R43, R44): once the meter that caused a freeze has reset (or no longer has lockout ahead, or the
            week is ≥ 100 − reserve: then wait, R44), release one frozen session every RESUME_STAGGER_MIN,
            label urgent first, then the oldest freeze
```

- **R36 (let a job finish with 1 % more) is not met in v1**: nothing tells how much a job still needs. A job labelled `big:<pct>` (e.g. `AGENT_QUOTA_JOB=big:3`) is left to run when `<pct>` fits under `100 − pct`; unknown needs are treated as large. → open point 1.
- **A session's share of the meter**: its $ over the last 30 min ÷ all sessions' $ on this machine × the meter's slope. This needs no $-per-% conversion. Use outside Claude Code (R34) stays in the meter's slope and is never a candidate.
- **Each machine decides for its own sessions** (R35): the meters are the account's, the $ per session is local (the tracker's `telemetry` is per machine). The VM runs the same hook.

## 5. Labels, overrides, modes

| How | Effect |
|---|---|
| `AGENT_QUOTA_JOB=big claude …` (or `big:<pct>`, `urgent`, `maximizer`) | the hook reads its own environment (a hook inherits the session's) and records the label (R40) |
| `agent-quota go-on <session>` | never freeze it until its window resets (R46) |
| `agent-quota resume-now <session>` | release it now (R46) |
| `agent-quota mode off|observe|on` | `observe` is the default: everything is decided and logged, nothing held (R3) |

## 6. Telling Jean (R45, R47)

- On a freeze: the hook calls `notify event …` (agent-notify) for its own pane, once, and writes `state/statusline.txt` (`⏸ 2 paused · resumes 19:00`) for agent-statusline to show (a change in agent-statusline, not here: open point 3).
- Every decision, held or not, is a line of `decisions.jsonl`: the readings, the projection, harm vs cost, each candidate and why it was or was not frozen (R47). `agent-quota status` prints the latest.

## 7. Why a hook that recomputes, not a scheduled job

The hook already runs on every tool call of every session, so a recompute at most every 60 s from inside it needs no new job, no LaunchAgent, no systemd unit; when no session is calling tools, nothing needs deciding. Rejected: a job every minute (one more service on two machines, and it would run when nothing is active).

## 8. Why the hook fails open

A bug in a hook with `onFailure:"block"` would block every tool call of every session: a lockout made by the protector itself. So `onFailure` stays unset and the code catches everything. The cost: a crash during a freeze releases that session early, which is no worse than having no protector. **[assumed; Jean to confirm]**

## Acceptance

- `pytest`-free unit tests (`python3 -m unittest`) on the pure parts: forecast, state, protector, with the worked examples of [`CONSIDERATIONS.md`](CONSIDERATIONS.md) §2–3 as cases (S1–S9).
- A replay on the tracker's real quota history: how many lockouts happened, how long, and what v1 would have frozen and when (`doc/replay.md`).
- An end-to-end test with `claude -p` (as `lab/i2_hook_hold/`): a decision `freeze` holds a session and its subagent; `resume-now` releases it within `HOLD_POLL_S`; `mode observe` never holds.

## Open points

| # | Question | Default in v1 |
|---|---|---|
| 1 | How much does a big job still need (R36)? | unknown = large; `big:<pct>` when Jean knows |
| 2 | Checkpoint (§6 of CONSIDERATIONS) as well as freeze? | freeze only: tested, zero tokens, keeps subagents |
| 3 | The status line shows `statusline.txt` | needs a change in agent-statusline (another repo) |
| 4 | Interactive sessions labelled nothing but burning fast | warned, never frozen |
| 5 | The VM: same hook, own telemetry | install there once the Mac has run in `observe` for a while |
