# Considerations — the protector

What the protector must weigh before anything is designed: what it protects, the scenarios, the costs of each mistake, what it needs to know, what is still unknown. **This file states no design choice, on purpose.** Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary. How it stays apart from the maximizer: [`../CONSIDERATIONS.md`](../CONSIDERATIONS.md) §2.

Contents: [1. What it protects](#1-what-it-protects) · [2. The question for each big job](#2-the-question-for-each-big-job) · [3. Scenarios](#3-scenarios) · [4. The cost of each mistake](#4-the-cost-of-each-mistake) · [5. What it needs to know](#5-what-it-needs-to-know) · [6. Ways to pause](#6-ways-to-pause) · [7. Resuming](#7-resuming) · [8. Anticipation](#8-anticipation) · [9. To investigate](#9-to-investigate) · [10. What any design must decide](#10-what-any-design-must-decide)

## 1. What it protects

> The main consequence of not pausing a big job, or of being too late while trying to do so, is that we end up in a long period of time where the user cannot use Claude Code at all, even if it's for a very urgent work that would not require a lot of tokens (like answering an important email). (Jean, 2026-11-11)

- **The protector protects Jean's small urgent work, not the quota.** What it avoids is a lockout. Lost quota is the maximizer's subject, not this one.
- **A lockout's harm depends on its length and on when it happens.** A lockout of 10 minutes, or one at 02:00 while Jean sleeps, costs almost nothing; a lockout of 2 h 30 in a working afternoon, or of 3 days because the week is at 100 %, is what must not happen.
- **The week is the bigger stake.** A window's lockout lasts at most 5 hours; the week's can last days (the week resets Monday 19:00 UTC).

## 2. The question for each big job

**Can it finish before the window (or the week) reaches 100 %?**

| Answer | Pausing it costs the job | Pausing it gives Jean |
|---|---|---|
| **no**: it will hit the limit anyway | almost nothing: it would wait for the reset in any case; a clean pause even saves it from being cut mid-request (§9, I1) | the reserve, until the reset |
| **yes, with room to spare** | a delay of up to 5 hours (week: days), for nothing | nothing: there was no lockout ahead |
| **yes, but only by eating the reserve** (Jean's example: 1 % more and it finishes) | a delay of up to 5 hours, plus a checkpoint and a resume | the small reserve it would have eaten |
| **unknown** | the hard case: most big jobs do not know how much they have left | — |

Worked example (Max 5x: 1 % of a window ≈ $1.94, measured 2026-10-12). At 13:00 the window is at 60 %, its reset at 16:00; a big job burns 1.3 % per minute and needs about 80 % more.

| | Paused at 92 % (13:25) | Not paused |
|---|---|---|
| the window reaches 100 % | never before the reset | 13:31 |
| Jean's lockout | none: 8 % left for small urgent work until 16:00 | **13:31 → 16:00 (2 h 29)** |
| the big job | waits 13:25 → 16:00, then resumes from its checkpoint | stuck 13:31 → 16:00 anyway, cut mid-request; subagents may lose their work |

Here pausing costs the job nothing: it could not finish in this window. Pausing is costly only when the job could have finished (rows 2 and 3 above).

## 3. Scenarios

| # | Situation | Without a protector | What Jean would want |
|---|---|---|---|
| S1 | window at 95 %; Jean asks one small question (≈ 0.5 %) | fine | it goes through, always |
| S2 | a big job has used 75 % of the window, now at 98 %; it needs ≈ 1 % to finish | it finishes at 99 % | let it finish (Jean, 2026-11-11): pausing would keep 2 % and delay it 5 h |
| S3 | the worked example of §2: 60 % at 13:00, 1.3 % per minute, ≈ 80 % still needed, reset 16:00 | lockout 2 h 29 | pause it, keep the reserve |
| S4 | the same, but the reset is at 13:40 | lockout 9 min | probably let it run: a 9-minute lockout is cheap |
| S5 | Friday 15:00, week at 90 %, its reset Monday 19:00; a big job burns 3 % of the week per hour | the week reaches 100 % at ≈ 18:20: **lockout ≈ 72 h** | pause long before; the week needs its own reserve |
| S6 | three medium jobs, none big alone, together 1.5 % per minute | as S3 | which one to pause? the least urgent, or the biggest burn rate? |
| S7 | use outside Claude Code (claude.ai, the phone, Cowork) pushes the window up | — | it cannot be paused: count it in the burn rate, pause something else |
| S8 | the maximizer launched optional tasks in a window's last hour; Jean then starts heavy work | both together reach 100 % before the reset | the maximizer's tasks are paused first: they are optional (R2) |
| S9 | a big job runs alone at night; the window resets at 03:00 | lockout 01:00 → 03:00 while Jean sleeps | maybe no pause: nobody needs Claude then |
| S10 | the quota reading is 20 minutes old (nobody's status line ran, the poller is late) | — | never pause, or never let run, on a stale number without saying so |
| S11 | a big job with 6 subagents running when the limit is hit | subagents cut mid-request, their work lost (seen by Jean) | the work stops cleanly before the limit and resumes after the reset |

## 4. The cost of each mistake

| Mistake | What it costs | Example |
|---|---|---|
| **pausing when there was no lockout ahead worth avoiding** | the big job delayed by up to 5 h (the week: days); the tokens of the checkpoint; the tokens of the resume (§7); a resume that may go worse than continuing | S2 paused: keeps 2 %, delays the job 5 h; S4, S9 paused for a lockout that would not have hurt |
| **pausing too late, or not at all** | **a lockout**: Jean cannot do small urgent work until the reset; the work cut mid-request is lost and redone | S3 not paused: 2 h 29; S5: ≈ 72 h |
| **pausing the wrong work** | Jean's small urgent work is stopped; an urgent job is delayed while a non-urgent one goes on | pausing the interactive session where Jean answers an email |
| **pausing, then failing to resume** | the job is lost, or Jean must restart it by hand | the session was closed, the checkpoint was incomplete |
| **a pause started too late to finish** | the checkpoint itself hits the limit: the worst of both | §8 |

The trade-off for a big job, in words: **the harm of the lockout avoided** (its length × how likely Jean needs Claude during it × how urgent that need is) against **the cost of the pause** (the delay × the job's urgency + checkpoint + resume). In S3 the first is large and the second near zero; in S2 the opposite.

## 5. What it needs to know

| Input | Where it could come from | Known today? |
|---|---|---|
| window and week %, their resets | the tracker's `quota_latest.json` | yes; freshness to check (§9, I3) |
| each session's burn rate | the tracker's per-session tokens and $ | mostly: `claude -p` reports tokens but no $ |
| which sessions are interactive, which are big jobs | the tracker's sessions (entrypoint, folder, pane) | yes |
| how urgent each piece of work is | Jean says it at launch; a `tasks` task's urgency; an interactive session = possibly urgent | **no** |
| how much a big job still needs | the agent's own estimate; Jean says it at launch; past runs of the same job | **no**: the hardest input |
| whether Jean is likely to need Claude now | Jean's own use by hour of day, measured (the maximizer measures Jean's last hour already: [`../maximizer/DESIGN.md`](../maximizer/DESIGN.md) §2) | measurable |
| what is outside Claude Code | the tracker's "unknown" | measured per window, after the fact |

## 6. Ways to pause

The options, not a choice.

| Way | How | Tokens | What is kept | Risks |
|---|---|---|---|---|
| no new work | a hook refuses new subagents and new tasks | none | everything | the work already running goes on |
| **freeze** | a hook holds the session before its next tool call, until the reset | none | everything, the subagents included (if hooks fire in subagents: I2) | hook time limit (I2); the machine must stay awake; a crash during the freeze loses it |
| **checkpoint** | the agent is told to checkpoint, to ask its subagents to checkpoint, then to stop | some | what the file says | slow: the agent waits for a good moment and for its subagents (§8); needs anticipation |
| `SIGSTOP` / `SIGCONT` | a signal from outside | none | everything | stopped in the middle of a request: the connection may be lost |
| kill, then `claude --resume` | — | none | the main session only | the subagents' work is lost: what Jean saw |

## 7. Resuming

- **When the limit is hit, work seems lost, not paused** (Jean saw subagents lose their work, not wait). Why exactly is to investigate (I1) before relying on it.
- **A resume after a long pause re-reads the whole context without cache**: the prompt cache lasts minutes to an hour, a pause lasts hours. A session with a large context pays it again in full: to measure (I4).
- **All paused work resuming at the reset could itself cause the next lockout** (a stampede): resuming one by one, by urgency, is worth considering.
- **A resume must check the week too**: resuming at a window's reset into a week near 100 % only moves the lockout.
- **Jean should know**: what was paused, why, when it resumes, and how to say "keep going".

## 8. Anticipation

A checkpoint is not instant: the agent waits for a good moment and for its subagents, and the checkpoint itself spends quota. So the protector's line moves with the burn rate and is not a fixed %.

Worked example: reserve 8 %, a checkpoint that takes 5 minutes and costs ≈ 2 %, a big job at 1.0 % per minute. The checkpoint must start when the window still has 8 + 5 × 1.0 + 2 = 15 % left, so at **85 %**, not 95 %. The same job at 0.2 % per minute: 8 + 1 + 2 = 11 % left, so at **89 %**. A freeze needs no such lead: it acts at the next tool call.

## 9. To investigate

Partly answered by the research of 2026-11-11: [`../doc/prior_work.md`](../doc/prior_work.md) §2.

| # | Question | Why it matters | Evidence so far |
|---|---|---|---|
| I1 | What exactly happens to a session and its subagents when the limit is hit mid-request? Can a cut subagent be continued? | decides whether "let it hit the limit" is ever acceptable | Jean saw subagents lose their work; a public issue reports the same ([claudeissues #89429](https://claudeissues.com/issue/89429-session-token-limits-repeatedly-kill-in-flight-subagents-mid-task-resume-ux-is-m)) → mostly answered in `../doc/prior_work.md` §2: a cut subagent can be continued by `SendMessage` to its id (docs, user-verified); still to see on Jean's machine |
| I2 | Can a PreToolUse hook hold a session for hours? Do hooks fire inside subagents, foreground and background? | decides whether a freeze is possible | not tested → partly answered in `../doc/prior_work.md` §2: hooks fire in subagents; `timeout` has no documented maximum and fails open unless `onFailure:"block"`; tested 2026-11-11: holds work in the main agent and in subagents, a timeout sends SIGTERM, `onFailure:"block"` then blocks the call; **a 5 h 05 min hold works** in the main agent and in a subagent (`claude -p`, 2026-11-11, `lab/i2_hook_hold/`); still untested: an interactive session, a background subagent, a sleeping Mac |
| I3 | How fresh is the quota % while a big job runs? `claude -p` runs no status line, so its own use reaches the reading only through other sessions or the tracker's poller | a pause decided on a stale reading (S10) | not measured |
| I4 | What does a resume after a 5-hour pause cost, for a large context? | the cost of every pause (§4) | not measured |
| I5 | How long does a checkpoint take with N subagents, and what does it cost? | the lead of §8 | not measured |
| I6 | What does Claude Code itself now do at the limit? A "graceful stopping point" was reported (2026-09-25, not confirmed from Anthropic) and `/config` has "Continue automatically at usage limit" (reported broken with several sessions) | it may cover part of this, or behave differently from what I1 finds | [`../doc/prior_work.md`](../doc/prior_work.md) §2 → answered in `../doc/prior_work.md` §2: auto-continue never covers the week (> 24 h) nor `-p`; the 95 % wrap-up parks sessions with nothing to resume them |

## 10. What any design must decide

- Which work may be paused, and in which order (urgency, burn rate, interactive or not, the maximizer's first).
- How it learns a job's urgency and what it still needs, and what it does when it does not know.
- The size of the reserve, for the window and for the week; whether a job that would finish may eat into it (S2), and by how much.
- How long a lockout, and at what time of day, is worth a pause (S4, S9).
- Freeze, checkpoint, or both; how far ahead it acts (§8).
- How work resumes, in which order, and how Jean is told and can override.
- How the protector's state is shared with the maximizer so that they never act together (R1).
