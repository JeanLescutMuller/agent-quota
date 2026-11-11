# maximizer — design (to build)

What the maximizer will do, how, and why: for Jean, to check the plan; for the agent who builds it. **State: to build.** Moved here from the `tasks` repo (`design/quota_maximizer.md`, where it was phase 4 = step 5 of `task-manager`) on 2026-11-11; "step 4", "step 5", "phase 2's launcher" and deep_cleaning below are the `tasks` repo's (`/Users/jeanlescut/dev/tasks/design/DESIGN.md`). Agreed with Jean: the gate (§2) and the order, deep_cleaning first, then launch (§3). Everything else is a proposal to validate before building; each section says which. It serves R15b, R15c, R23, R24, R25, R28 ([`REQUIREMENTS.md`](REQUIREMENTS.md)); the picture of an earlier version: [`DESIGN.html`](DESIGN.html) (a snapshot, not regenerated since the move). Words: the vocabulary of [`../AGENTS.md`](../AGENTS.md).

**The principle: quota Jean pays for and does not use is lost at the weekly reset. Spend it on agents' optional work, as late as possible, so Jean keeps first claim on everything until it is about to be lost.**

Contents: [1. The step at a glance](#1-the-step-at-a-glance) · [2. The gate](#2-the-gate) · [3. deep_cleaning first, then launch](#3-deep_cleaning-first-then-launch) · [4. Which tasks it starts](#4-which-tasks-it-starts) · [5. How much it starts](#5-how-much-it-starts) · [6. Measuring B and B_week](#6-measuring-b-and-b_week) · [7. Who used the quota](#7-who-used-the-quota) · [8. Plan changes](#8-plan-changes) · [9. Seeing why, switching it off](#9-seeing-why-switching-it-off) · [10. Claude only](#10-claude-only) · [11. What was measured](#11-what-was-measured) · [12. Starting values](#12-starting-values) · [Acceptance](#acceptance) · [Open points](#open-points)

## 1. The step at a glance

| | |
|---|---|
| Step | 5 `Quota maximizer` (slug `quota-maximizer`) of the job `task-manager`, every 5 min, on the VM |
| Reads | the tracker's view `latest` (`~/opt/agent-tracker/data/claude/account_quotas.db`, read-only); deep_cleaning's result (the optional tasks deep_cleaning C8 picked); step 1's download of Todoist; this project's run records (`~/opt/tasks/state/runs.jsonl`) |
| Writes | claims and launches through phase 2's launcher; one record per run (§9); the measures of §6–§7 |
| Acts | **yes**: starts Claude agents, read-only, paid by quota that would otherwise be lost |
| Consumed by | Jean (the records, the measures); the launched tasks' outcomes, written by the launcher |

```
step 5, every 5 min, VM
  gate       code reads view `latest`:  (last hour of the current window  OR  no window open)
                                   AND  spare quota this week > 0                                   §2
  first      no deep_cleaning in this window → step 4 starts one in the background; step 5 waits      §3
  launch     deep_cleaning's result read → the optional tasks it picked, in its order,
             each checked by code, while their estimates fit in the spare quota                     §4, §5
             → claim + phase 2's detached launcher (read-only)
  record     one file: the readings, each check, what was launched and why                          §9
```

## 2. The gate

**Agreed with Jean.** Code, every run, from view `latest` of the tracker; no AI.

```text
open  ⇔  ( now ≥ five_hour_resets_ts − 1 h     # the last hour of the current window
           OR five_hour_resets_ts is NULL )      # no window open: nobody is working, nothing of Jean's to protect
     AND spare > 0
spare =  (100 % − seven_day_pct) × B_week  −  (hours until seven_day_resets_ts ÷ 5) × B
```

`spare` asks: even if every window left this week were used in full, would quota still be lost at the reset? `latest` already reads a window whose reset has passed as 0 %, with a NULL reset time (the tracker's rule 8).

**Worked example** with B = $194 and B_week = $1,469 (measured on Max 5x):

| When | `seven_day_pct` | Week left | Windows left × B | Spare | Gate |
|---|---|---|---|---|---|
| Thursday 19:00 UTC (96 h to the reset) | 40 % | 60 % × $1,469 = $881 | 96 ÷ 5 = 19.2 × $194 = $3,725 | none | closed |
| Monday 15:00 UTC (4 h to the reset) | 70 % | 30 % × $1,469 = $441 | 4 ÷ 5 = 0.8 × $194 = $155 | $441 − $155 = $286 | open, in the last hour of a window or with none open |

**Why the last hour of a window:** Jean may use any window personally; launching at its start would take quota Jean might want. In the last hour Jean has had four hours, and what is left of the window is about to reset anyway.

**Why no day-of-week rule:** the numbers decide. A week holds only 7.6 full windows of $ ($1,469 ÷ $194) but lasts 33.6 window lengths, so early in the week the gate finds no spare by itself.

**Jean's own work in that last hour** (proposed, for Jean to validate): the last hour is when the step launches, but Jean may also be working then. Two guards, both measured, none guessed:

| Guard | Rule | Example (B = $194) |
|---|---|---|
| a share kept for Jean | `spendable = spare − jean_last_hour`, where `jean_last_hour` is the 90th percentile of Jean's own $ in the last hour of his windows over the last 4 weeks (Jean's own: slots with entrypoint `cli`, §7); until 4 weeks are measured: 25 % of B | spare $286, Jean's 90th percentile $40 → spendable $246 |
| Jean working right now | Jean's own slots show use in the last 10 min → this run launches nothing new; agents already running go on | Jean opens a session at 18:20 in the last hour: no launch at 18:20, 18:25… until 10 min after his last use |

**Rejected:** opening a window on purpose to start its clock (it adds no quota: the week is the limit).

## 3. deep_cleaning first, then launch

**Agreed with Jean.** Step 4 runs before step 5 in every run. When step 5's gate opens and no deep_cleaning ran in this window, step 4 starts one in the background (`tasks` repo: `design/deep_cleaning.md`); it reviews all the open tasks and its result lists the optional tasks to start, in launch order (deep_cleaning C8). A later run's step 5 (≤ 10 min) reads that result and launches. Later runs of the same window launch from the same result. One deep_cleaning per window; one started for step 5 counts as the day's (the 03:00 one is then skipped).

## 4. Which tasks it starts

**Agreed:** only optional work, picked by deep_cleaning's review: an optional one-off task with no planned date, or a recurrent task (oldest `last_done_dt` first). Never an idea, never a required task (those are step 3's, on their planned date).

**Proposed:** code checks each picked task again just before launching it; a task that fails a check is skipped.

| Check | Why |
|---|---|
| still open, not `in-progress`, not `blocked` | as step 3 |
| owner `claude` or `any_agent` | the only owners this step can start |
| every `depends_on` task completed, `wait_until` passed | as step 3 |
| `execution_environment` `vm` or `any` | the job runs on the VM |
| its estimate fits in the spare left (§5) | never spend quota that is not spare |

The launch itself is phase 2's: the claim, a detached launcher, read-only, the outcome written by the launcher (`tasks` repo: `doc/task_manager.md`). A task always finishes: a reset during its run changes nothing; the next run decides again.

## 5. How much it starts

**Proposed** (carried over from the legacy quota maximizer, adapted to the agreed gate).

```text
spare_left  = spare − jean_last_hour (§2, Jean's own work)
running     = agents this step launched that are still running
for each picked task, in deep_cleaning's order:
    estimate = its duration × the median $ per minute of past runs
    stop if  running ≥ MAX_PARALLEL_TASKS_PER_SUBSCRIPTION
    skip if  estimate > spare_left  or  spare_left < MIN_TASK_BUDGET
    skip if  the 5-hour window is above 90 %          # the same guard as step 3
    stop if  Jean's own slots show use in the last 10 min   # Jean is working: launch nothing new (§2)
    launch;  spare_left −= estimate;  running += 1
```

Two limits, never multiplied: the quota (the spare) and the time (what the agents at once can spend before the reset: agents × burn rate × hours left). The smaller wins.

**The burn rate** is measured from the run records: $ ÷ duration of each run (`total_cost_usd` from `claude -p --output-format json`). The worst case is its slow end, the 10th percentile of the last runs, once `MIN_BURN_SAMPLES` runs exist; until then $32 per hour [assumed]. It sets how many agents at once can spend a given amount in time:

| Agents at once (at $32 per hour) | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| time to spend $145.63 (75 % of a Max 5x window) | 4 h 33 | 2 h 17 | 1 h 31 | 1 h 08 |
| $ spent in the last hour of a window | $32 | $64 | $96 | $128 |

## 6. Measuring B and B_week

**Proposed; the method is carried over from the legacy quota maximizer and stated here in full.** The tracker stores facts only (Categories 1 and 3); "how many $ a window holds, and who used them" is Category 4, the reader's job.

| Quantity | Measured as | Max 5x |
|---|---|---|
| **B**, $ per full 5-hour window | per closed window: its $ ÷ its peak % × 100; the median of the last 10 windows since the last plan change that peaked at 30 % or more; inside the open window, once it reached 20 %, its own value wins | $194.17 (p10–p90 $179–202) |
| **B_week**, $ per full week | the week's $ ÷ its % × 100, once the week reached 20 %; before that, the last week's | $1,469 |

**The $ of a window** = the `usd` of the tracker's slots (Claude Code's own figure, every machine: on the VM the `slots` of every file in `~/opt/agent-tracker/data/claude/aggregates/`, `UNION ALL`) **plus the `total_cost_usd` of this project's runs**, because `claude -p` sends no telemetry: its slots carry tokens but no $. Where neither gives a $, no $ is computed (the tracker's rule 7): those slots are counted in tokens only.

**Reading the tracker** (its `FOR_READERS.md`): open read-only with `PRAGMA query_only = ON`; read new rows by `rowid` (one watermark per database file), never by time; a % is account-wide; never compare a % across plans; a passed reset reads 0 %; within one window the % never decreases. A window is measured once closed and every machine's slots reach its end (the Mac's arrive when it wakes); after 24 h it is measured anyway, the missing part counted as unknown.

**The tracker's aggregation on the VM** turns each machine's transcripts into slots (about 1 s, incremental). Proposed: step 5 runs it itself, after its gate opens (`python3 ~/opt/agent-tracker/src/aggregate_slots.py`), and the tracker's own VM trigger is removed the same day (two runs at once would read the same bytes); the Mac's trigger stays. Why: its only reader on the VM is this step.

## 7. Who used the quota

**Proposed.** Serves R24. Each closed window and each week gets one row, in $ and in units, in `~/opt/tasks/data/claude/windows.csv` and `weeks.csv`.

| Who | Recognised by |
|---|---|
| agent tasks | this project's run records (`~/opt/tasks/state/runs.jsonl`) and their slots in `~/opt/tasks/work/<task id>/` |
| production jobs | slots whose folder is a declared production job's (below) |
| Jean | slots with entrypoint `cli` (an interactive terminal) in any other folder |
| other scripted use | `sdk-cli` or `sdk-py` slots in a folder no production job declares: the record says "declare this production job" |
| **unknown** | what the meter moved (peak % × B) minus all of the above: claude.ai, the apps, cloud sessions, an untracked machine. Per week, the API's `seven_day_breakdown` splits out chat and cowork |

**Production jobs that use quota** are never tasks, so they are declared in a list: name, machine, folder, schedule (today: auto-job-apply, once a day, Sonnet and Haiku). Their $ per run is measured from the slots of that folder.

## 8. Plan changes

**Proposed.** Serves R25. A 7-day % that falls while its reset has not passed (Pro → Max 5x put both meters to 0 % mid-week), or a change of plan in the API's raw rows, starts measuring afresh: nothing before is mixed with what comes after. Until the open window reaches 20 %, B is unknown and **nothing is spent**.

## 9. Seeing why, switching it off

**Proposed.** Serves R23 and R28.

- **One record per run of step 5**, kept 14 days: the readings, B and B_week used, the gate's three parts, each picked task with its check results and estimate, what was launched. "Why did it spend $12 at 03:12?" is one file to open. The run's summary line on job-runner's dashboard says the gate's state and what was launched.
- **Never on stale numbers:** the newest quota reading older than `READING_MAX_AGE_SECONDS`, or B or B_week unknown → nothing launched, the record says why.
- **Its own switch**, like the steps already built: `"quota_maximizer": {"mode": …}` in `conf/task-manager.json`, `dry-run` by default (what it would launch goes to a log, nothing is claimed or started), `apply` once Jean agrees. Switching it off leaves steps 1–4 running.

## 10. Claude only

**Proposed.** The gate and the spending plan the Claude subscription only. Codex's spare quota is not planned: the tracker keeps Codex's data on the Mac outside its categories, and Codex is not on the VM. A task owned by `chatgpt` is never started by this step.

## 11. What was measured

The tracker's analysis of the first full Max 5x week (run 2026-10-12, $ = Claude Code's own):

| Measure | Pro | Max 5x |
|---|---|---|
| B, median | $47.29 (6 windows) | **$194.17** (7 windows) |
| B_week | $357 (one week, cut at 60 %) | **$1,469** |
| B_week ÷ B (full windows a week holds) | 7.55 | **7.57** |
| 1 % of a 5-hour window | $0.47 | $1.94 |
| Max ÷ Pro | — | **4.11×, not 5×**, on both meters |

| Fact | Why it matters here |
|---|---|
| **The week is the limit, not the window**: 168 h = 33.6 window lengths, but only 7.6 full windows of $ | quota is lost at the weekly reset (Monday 19:00 UTC); what can spend it is the last windows before it |
| The first Max week ended at 69 %: $1,022 used, **31 % ≈ $455 lost**; all of it interactive work on the Mac | the size of what this step can recover |
| The 7-day meter sometimes jumps faster than any 5-hour use explains (20 % → 27 % in 13 min; 7 % → 18 % in 9 min) | a reading of the week's % may show a sudden loss of room: read it every run |
| 7 windows opened with no activity in either machine's slots | usage outside Claude Code is real: the "unknown" row of §7 |
| Claude Code reports a $ only for interactive sessions; `claude -p` and Agent SDK sessions send no telemetry | the $ of this project's runs comes from their own `total_cost_usd` (§6) |
| The burn rate of a launched agent is not measured yet | $32 per hour is an assumption until `MIN_BURN_SAMPLES` runs |

## 12. Starting values

Carried over from the legacy quota maximizer; each is re-checked once runs are measured.

| Parameter | Value | Owner | From |
|---|---|---|---|
| `READING_MAX_AGE_SECONDS` | 600 | the gate (§9) | never spend on stale numbers |
| `BOT_WORST_CASE_BURN_USD_PER_HOUR` | the 10th percentile of the last runs; $32 until then | §5 | the legacy "1 unit per hour on Pro", in $ |
| `MIN_BURN_SAMPLES` | 10 runs | §5 | legacy |
| `MAX_PARALLEL_TASKS_PER_SUBSCRIPTION` | 3 | §5 | 3 agents spend 75 % of a window in 1 h 31 |
| `MIN_TASK_BUDGET` | 0.05 unit ($9.71 on Max 5x) | §5 | legacy |
| records kept | 14 days | §9 | legacy |

Measured, never parameters: B, B_week, each production job's $ per run, the burn rate.

## Acceptance

- Thursday 19:00 UTC at 40 % of the week: the gate is closed; the record says "no spare: the windows left hold $3,725, the week $881".
- Monday 15:00 UTC at 70 %, in the last hour of a window: deep_cleaning runs; a later run launches the picked tasks, in order, until their estimates reach $286.
- Jean working in the first four hours of a window: nothing is launched.
- The newest reading is 11 minutes old: nothing is launched; the record says why.
- After a plan change: nothing is spent until the open window reaches 20 %.
- Switched off: steps 1–4 go on as before.
- A launched task still running at the window's reset finishes; the next run decides again.

## Open points

| # | Question | Claude's recommendation |
|---|---|---|
| 1 | Is the VM's copy of the readings fresh when Claude Code is used only on the Mac? (fresh on 2026-11-02) | check the age of `latest` on the VM over a week before building |
| 2 | Windows left are counted as hours until the reset ÷ 5: should Jean's expected use be subtracted? | no: it only makes the gate open later; measure first |
| 3 | The gate ignores work already committed: due agent tasks (step 3) and production jobs before the reset | subtract their measured $ once §7 measures them |
| 4 | A task started in the last hour may run past the window's reset and open Jean's next window | cap a launch's estimate at what fits before the reset, or accept it: measure how often it happens |
| 5 | Tasks that must run on the Mac (`execution_environment: macbook`) | not started by this step at first; the Mac's job could pick them later |
| 6 | How many agents at once, and the time limit of each | 3 at once to start; set once the burn rate is measured |
