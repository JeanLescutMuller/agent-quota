# Replay: the protector v1 on Jean's real quota history

What the protector v1 ([`../protector/DESIGN.md`](../protector/DESIGN.md) §3–§4) would have done on Jean's Max 5x history (2026-10-07 16:51 → 2026-11-16 17:46 UTC, 40.0 days), minute by minute, with the repo's own `forecast.py`, `state.py` and `protector.py`, unchanged. Written 2026-11-16 by Claude. Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary.

**Headline: 8 lockouts happened (43.4 h in all, one of them the week: 28.6 h). v1 as designed would have frozen nothing and avoided none, because 98 % of the $ comes from interactive sessions, which v1 never freezes. Freezing the subagents of an interactive session (never Jean's own main thread) would have avoided 7 of 8, for 76 freeze-hours and $119 of delayed work over 40 days. LOCKOUT_VS_DELAY changes nothing between 3 and 30.** Since then built as v1.1 (§9): the same 7 of 8, Jean's main thread never frozen.

## Words used here (new ones)

| Word | Means |
|---|---|
| **v1** | the rule as designed: interactive sessions are never frozen (R32); a script (`claude -p`) burning ≥ 10 % of a window per hour is a candidate |
| **subagents** | v1, plus: the subagents of an interactive session are a candidate of their own, judged by their burn rate; a freeze holds them, never Jean's main thread |
| **burn** | v1, plus: an interactive session itself is a candidate while it burns ≥ 10 % of a window per hour (as if Jean had labelled it `big`) |
| **freeze-hours** | the sum, over every frozen session (or subagents), of the hours it was held |
| **false alarm** | a freeze whose meter, in the real history, never reached 100 % |
| **late** | a freeze decided when the meter was already in the reserve (≥ 100 − reserve) |

## 1. What was measured

| | |
|---|---|
| Quota readings | the tracker's `account_quotas` (statusline + API poller, both machines), Max 5x only (tracker rule 11): 54,409 rows → 7,392 window and 547 week changes after cleaning |
| $ per session | the tracker's `telemetry` on the Mac: 107,502 requests, $6,662; the VM's telemetry is on the VM and is not here |
| Cleaning | rule 10 (a % never falls within one window), except a fall of ≥ 10 points that every reading of the next 15 min confirms (the week was reset early by Anthropic on 2026-11-13 17:47 UTC, its reset time unchanged); a statusline row is timed by when it was written (its `ts` can lag its % by up to a day) |
| Replay | one tick per minute (57,655); at each tick: the shared check (who acts), then `protector.decide()`; closed loop: a frozen session's requests are taken out of the history while it is frozen, and its $ off both meters ($1.94 per 1 % of a window = B / 100; $14.69 per 1 % of the week) |
| Jean typing | a new prompt in an interactive session's main thread (`repl_main_thread`, new `prompt.id`) |
| Scripts | [`../lab/replay/`](../lab/replay/): `data.py` (reads, cleans) → `lockouts.py` → `replay.py` (27 runs: 3 variants × 9) → `analyze.py` (these tables); outputs in `lab/replay/out/` (gitignored) |

## 2. The lockouts that happened

8 lockouts in 40 days: 7 of a window (883 min in all, median 94 min, max 282 min) and 1 of the week (1,718 min). 5 of the 8 fell in 3 days, Mon 9 – Wed 11 Nov. Times are Zürich time.

| Start | Meter | Length (min) | Jean typed in the 30 min before (prompts) | Jean typed during (prompts) | Requests refused (429), from interactive sessions | Mac $ in the hour before | Who burned most in the hour before |
|---|---|---|---|---|---|---|---|
| Tue 13 Oct 12:53 | window | 106 | 47 | 9 | 34 | 105 | trading-bot (interactive, $105) |
| Tue 13 Oct 18:47 | window | 52 | 3 | 0 | 0 | 7 | trading-bot (interactive, $7) |
| Sun 25 Oct 15:22 | **week** | **1,718** (28.6 h, to Mon 20:00) | 0 | 0 | 0 | 4 | secrets-and-account-migration (interactive, $4) |
| Mon 9 Nov 19:50 | window | 19 | 12 | 0 | 0 | 54 | job-applications ($36), communication-gateway ($14) |
| Tue 10 Nov 10:37 | window | 282 | 16 | 3 | 18 | 103 | job-applications ($40), trading-bot ($26), communication-gateway ($12) |
| Tue 10 Nov 16:16 | window | 243 | 7 | 3 | 34 | 87 | communication-gateway ($71) |
| Tue 10 Nov 23:46 | window | 94 | 20 | 3 | 8 | 40 | job-applications ($28) |
| Wed 11 Nov 12:43 | window | 87 | 6 | 3 | 18 | 38 | job-applications ($30) |

- Jean was typing in the 30 min before 7 of the 8 lockouts, and hit 5 of them while working (112 requests refused in all). The week's lockout (a Sunday afternoon to Monday evening) saw no use of the Mac at all.
- One more window reached 99 % (Mon 9 Nov 23:46) without locking out.
- The Tue 10 Nov morning window read 58 % at its first reading, 10 min after it opened, and was at 100 % 8 min later: the earliest a protector could have acted was 58 %.
- 269 of the 278 refused requests (429) on the Mac fall inside these lockouts; the other 9 are one burst of parallel requests on 11 Nov 10:32 (a rate limit, not the quota).

## 3. Who burns

| Mac $, all 40 days | $ | Share |
|---|---|---|
| interactive sessions, main thread | 4,407 | 66 % |
| interactive sessions, their subagents | 2,130 | 32 % |
| scripts (`claude -p`) | 129 | 2 % |

| Lockout start | Mac $ in the hour before | Share from scripts | Share from subagents |
|---|---|---|---|
| Tue 13 Oct 12:53 | 105 | 0 % | 78 % |
| Tue 13 Oct 18:47 | 7 | 0 % | 0 % |
| Sun 25 Oct 15:22 (week) | 4 | 0 % | 0 % |
| Mon 9 Nov 19:50 | 54 | 0 % | 48 % |
| Tue 10 Nov 10:37 | 103 | 0.8 % | 57 % |
| Tue 10 Nov 16:16 | 87 | 0 % | 56 % |
| Tue 10 Nov 23:46 | 40 | 0.3 % | 67 % |
| Wed 11 Nov 12:43 | 38 | 1.8 % | 74 % |

**The big jobs that caused the lockouts were interactive sessions running subagents, not scripts.** v1 can only freeze scripts (or sessions labelled `big`, and nothing was labelled), so it has nothing to freeze.

## 4. The replay, at the starting values (LOCKOUT_VS_DELAY 10, reserve 5 %)

| | v1 | subagents | burn |
|---|---|---|---|
| Lockouts avoided (of 8) | 0 | **7** | 8 |
| Lockout minutes left (sum; 2,601 in the history) | 2,598 | 52 | 0 |
| Freeze events (one meter, one window or week) | 0 | 9 | 10 |
| Freezes (sessions or subagents held) | 0 | 11 | 28 |
| Freeze-hours (sum) | 0 | 76 | 115 |
| Work delayed ($ the frozen ones would have spent while held; B = $194) | 0 | 119 (0.6 B) | 210 (1.1 B) |
| Jean's own main thread frozen | never | **never** | 28 times |
| False-alarm events (meter never reached 100 %) | 0 | 1 (Tue 20 Oct, peak 95 %) | 2 (Tue 20 Oct 95 %; Mon 9 Nov 99 %) |
| Late freezes (decided inside the reserve) | 0 | 1 (the week, at 95.7 %) | 3 |
| Highest meter reached after the freezes (max over the 8) | 102 % | 100 % (the one missed) / 98.6 % (the week) | 95.5 % |

When the freeze came, per lockout (subagents variant):

| Lockout | First freeze | Before the lockout | Meter at the freeze | Held | Meter's peak in the replay |
|---|---|---|---|---|---|
| Tue 13 Oct 12:53 | 12:47 | 6 min | 82 % | 1.8 h | 88 % |
| Tue 13 Oct 18:47 | — (no subagents were running) | — | — | — | 100 %: not avoided |
| Sun 25 Oct 15:22 (week) | Sat 24 Oct 21:43 | 17.6 h | 95.7 % (late) | **47.3 h** | 98.6 % |
| Mon 9 Nov 19:50 | 19:40 | 10 min | 87 % | 0.5 h | 96.5 % |
| Tue 10 Nov 10:37 | 10:30 | 7 min | 58 % | 3 × 4.7 h | 86.7 % |
| Tue 10 Nov 16:16 | 16:13 | 3 min | 87 % | 4.1 h | 94.4 % |
| Tue 10 Nov 23:46 | 23:40 | 6 min | 91 % | 1.7 h | 95.7 % |
| Wed 11 Nov 12:43 | 12:23 | 20 min | 92 % | 1.7 h | 93.9 % |

- Freezes come 3–20 min before a window's lockout: near the end the meter climbs 1–2 % per minute, so the 5-min look-ahead (`pct + rate × 5 min ≥ 100 − reserve`) is just in time, not early.
- The meter keeps climbing 2–10 points after the freeze (Jean's own work, the VM, claude.ai; 29 points on Tue 10 Nov, frozen at 58 %): that is what the reserve absorbs.
- A freeze for the week holds its job for about 2 days (Saturday evening to Monday 20:00); the week was saved by 1.4 points only.

## 5. Sensitivity: LOCKOUT_VS_DELAY and the reserve

| Variant | Reserve | Avoided (of 8) | Freeze-hours | Work delayed ($) | False-alarm events | Late freezes | Highest replayed peak |
|---|---|---|---|---|---|---|---|
| v1 | 3, 5, 10 % | 0 | 0 | 0 | 0 | 0 | 102 % |
| subagents | 3 % | 7 | 71 | 103 | 1 | 1 | 100 % (missed) |
| subagents | **5 %** | 7 | 76 | 119 | 1 | 1 | 100 % (missed) |
| subagents | 10 % | 7 | 83 | 173 | 1 | 1 | 100 % (missed) |
| burn | 3 % | 8 | 106 | 169 | 2 | 1 | 97.5 % |
| burn | **5 %** | 8 | 115 | 210 | 2 | 3 | 95.5 % |
| burn | 10 % | 8 | 178 | 313 | 2 | 5 | 93.6 % |

- **LOCKOUT_VS_DELAY 3, 10 and 30 give the same freezes, to the minute, in every row.** At each freeze the harm (lockout minutes × chance Jean needs Claude × LOCKOUT_VS_DELAY) was 8 to 300 times the cost (minutes until 100 %), so LOCKOUT_VS_DELAY would have to fall below ≈ 1.2 to change a decision. The decision is made by the reserve trigger alone.
- The reserve moves the cost, not the result: 3 → 10 % adds 17 % freeze-hours (subagents) to 68 % (burn), mostly from the week's freeze, which starts days earlier (burn, 10 %: 108 freeze-hours for the week alone).
- 10 % gives more late freezes, not fewer: the meter jumps by whole points, and the week climbs about 0.01–0.1 % per minute, so 5 min of look-ahead adds less than one point and the trigger fires only once the reading is already inside the reserve.

## 6. The shared check: who acts

| Who acts (v1, 57,655 minutes) | Minutes | Share |
|---|---|---|
| protector (lockout ahead on the window or the week) | 30,240 | 52.4 % |
| nobody (incl. 11.6 % with no reading younger than 10 min) | 23,699 | 41.1 % |
| maximizer (spare quota on the week) | 3,716 | 6.4 % |

| Meter | Minutes with "lockout ahead" | Lives flagged (windows, weeks) | Lives that really reached 100 % | Flagged minutes in a life that reached 100 % |
|---|---|---|---|---|
| window | 6,015 (10.4 %) | 65 | 7 | 27 % |
| week | 29,298 (50.8 %) | 7 of 7 | 1 | 28 % |

| Burn rate rule for the week (minutes with a fresh reading) | Flagged | Weeks flagged | Precision | Flagged the week that locked out from |
|---|---|---|---|---|
| DESIGN §2: max(30-min slope, average since it opened) × 1.5 | 57 % | 7 | 28 % | Tue 20 Oct (5 days before) |
| average since the week opened × 1.0 | 39 % | 5 | 36 % | Tue 20 Oct |
| slope over the last 48 h × 1.0 | 24 % | 4 | 58 % | Wed 21 Oct (4 days before) |

- The week says "lockout ahead" half the time and was right once: Jean front-loads the week, so any rate projects past 100 %. It is harmless in v1 (a freeze also needs the reserve about to be touched) and costs the maximizer little: of the 4,786 minutes with spare quota on the week, 30 went to the protector because of the week alone, 1,040 because of a window.
- It does make the status line and the decision log say "lockout ahead on the week" most of the time, which teaches Jean to ignore it.

## 7. What it means for DESIGN §2

| Parameter or rule | Starting value | What the replay says | Suggestion (for Jean to decide) |
|---|---|---|---|
| Candidates: interactive sessions never frozen (R32) | — | v1 avoids 0 of 8: there is nothing else to freeze | make an interactive session's **subagents** a candidate (7 of 8 avoided, Jean's main thread never held); R32 stays true for what Jean types |
| `LOCKOUT_VS_DELAY` | 10 | no effect from 3 to 30 | keep 10; it starts to matter only if `cost` counts the whole hold until the reset rather than the minutes until 100 % |
| `RESERVE_WINDOW_PCT`, `RESERVE_WEEK_PCT` | 5, 5 | after every window freeze the meter peaked at ≤ 96.5 %: 3.5 points or more were left | keep 5 |
| `REACT_MIN` (look-ahead, 5 min) | 5 | windows: 3–20 min of warning, enough; the week: late, inside the reserve | for the week, act from `100 − reserve − 1` or look 60 min ahead |
| Week burn rate (`RECENT_MIN` 30, `RATE_FACTOR` 1.5) | — | flags 51 % of minutes, right once | for the week, the slope over the last 48 h (precision 58 %), or show the week's "lockout ahead" only within a day of 100 % |
| A week freeze | until the week's reset | held 47 h, saved the week by 1.4 points | tell Jean at the freeze: it is a 2-day pause (R45) |
| `P_NEED_ACTIVE`, `P_NEED_IDLE` | 0.52, 0.13 | Jean typed in the 30 min before 7 of 8 lockouts; changes no decision (see `LOCKOUT_VS_DELAY`) | keep |
| `BIG_JOB_PCT_PER_HOUR` | 10 | not varied | — |

## 8. Caveats

- **The protector would have changed the history it is replayed on.** A frozen job's work is not added back after its release; in reality it would land in the next window and could start the next lockout (5 lockouts in Nov 9–11 were back to back). Jean, told of a pause, may also have worked differently.
- **The Mac only.** The VM's sessions cannot be frozen here (their $ is on the VM): they stay in the meter like claude.ai (R34). On the Mac, 1 % of a window matched $1.70 of Mac $ (median over 71 windows; p10 $1.12, p90 $2.07; $1.28 in the week of Nov 9) against B / 100 = $1.94, so the rest came from elsewhere, and a freeze's effect is converted at $1.94 per % (it removes fewer points than it may really have).
- **Small sample.** 8 lockouts, 5 of them in 3 days; nothing was fitted (a grid of 9 points per variant), so no split by calendar time was needed; once a parameter is fitted on this history, the legacy lab's split applies ([`prior_work.md`](prior_work.md) §3).
- **Proxies.** "Interactive" = a session with a request from the REPL's main thread; "Jean typed" = a new prompt there (task notifications count too); no session was ever labelled.
- **Ticks.** One decision per minute; the real hook decides only on tool calls (and its held calls' polls).
- **Readings.** Whole percents; a statusline row timed by its write time; the week's early reset of 2026-11-13 handled as a reset.

## 9. v1.1: the rule as built (2026-11-16)

v1.1 ([`../protector/DESIGN.md`](../protector/DESIGN.md) §4, "As built" 9–10) makes two changes, replayed here with the repo's own `decide()` and `burn_rate()` (`replay.py v1.1 v1.1-week30`):

| Change | What |
|---|---|
| subagents | an interactive session not labelled `urgent` (or `big`) is a candidate; its freeze holds only its subagents' tool calls; it is judged by its subagents' $ only (`query_source` `agent:*` in the tracker's `telemetry`) and frozen after every script |
| week rate | the week's slope looks back 48 h (`WEEK_RECENT_H`), not 30 min; still max with its average since it opened, × 1.5 |

| At LOCKOUT_VS_DELAY 10 | Reserve 3 % | Reserve **5 %** | Reserve 10 % |
|---|---|---|---|
| Lockouts avoided (of 8) | 7 | **7** | 7 |
| Lockout minutes left (2,601 in the history) | 52 | 52 | 52 |
| Freeze-hours (sum) | 71 | **76** | 83 |
| Work delayed ($ the frozen subagents would have spent while held; B = $194) | 103 | **119** (0.6 B) | 173 |
| Jean's own main thread frozen | 0 | **0** | 0 |
| False-alarm events (meter never reached 100 %) | 1 | 1 (Tue 20 Oct, peak 95 %) | 1 |
| Late freezes (decided inside the reserve) | 1 | 1 (the week, at 95.7 %) | 1 |

- **Identical, run for run, to the "subagents" variant of §4–§5**: the decision in the code makes the same freezes at the same minutes. All 11 freezes (reserve 5 %) hold an interactive session's subagents; the missed lockout (Tue 13 Oct 18:47) still had no subagent running. LOCKOUT_VS_DELAY 3, 10, 30: the same freezes again.
- **The week's 48 h slope changes no freeze** (`v1.1-week30`, the same rule with the old 30 min: the same numbers): a freeze needs the reserve about to be touched, and the week reaches it only at 95.7 % either way.

What the 48 h slope did to "lockout ahead" on the week (the replayed meter, minutes with a fresh reading):

| Week burn rate | Flagged | Precision (flagged minutes in the week that reached 100 %) | First flag of the week that locked out | Who acts: protector / maximizer / nobody (all minutes) |
|---|---|---|---|---|
| v1's rule: max(30-min slope, average) × 1.5 (`v1.1-week30`) | 56.9 % | 28 % | Tue 20 Oct 11:02 | 51.9 / 6.6 / 41.5 % |
| **v1.1: max(48 h slope, average) × 1.5** | **51.2 %** | **30 %** | Tue 20 Oct 17:59 | 48.6 / 6.6 / 44.8 % |

- **A small gain, not the 58 % of §6**: there, the 48 h slope was taken alone and × 1.0. Kept as max with the average and × 1.5, the average × 1.5 decides most minutes: Jean front-loads the week, so its average projects past 100 %. On the history (no protector), the same rule × 1.0 flags 39 % (precision 36 %), the 48 h slope alone × 1.0 36 % (40 %); counted here as the replay feeds `burn_rate`, which differs from §6's count at a week's start.
- The replay now also passes `burn_rate` the first reading after a reset inside the look-back: before, the week's early reset of 2026-11-13 (reset time unchanged) read as re-opened at every tick, 48 h of pct ÷ 10 min.

## Rerun

```sh
cd /Users/jeanlescut/dev/agent-quota/lab/replay
python3 data.py > out/data.log 2>&1 && python3 lockouts.py > out/lockouts.log 2>&1 && python3 replay.py > out/replay.log 2>&1 && python3 analyze.py > out/analyze.log 2>&1
python3 replay.py v1.1 v1.1-week30 > out/replay_v1_1.log 2>&1   # §9 only: out/summary_v1.1_v1.1-week30.csv
```

§2–§8 were measured before v1.1, with the week's 30-min slope; a full rerun now replays every variant with the 48 h slope (freezes unchanged for v1.1; §6's minutes would move as in §9).
