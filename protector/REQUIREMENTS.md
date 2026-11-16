# Requirements — the protector

From Jean's point of view only: the benefit, never the mechanism. Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary. The requirements shared with the maximizer (R1–R5): [`../REQUIREMENTS.md`](../REQUIREMENTS.md). What led here: [`CONSIDERATIONS.md`](CONSIDERATIONS.md). Numbered from R30 so that no number repeats one of the maximizer's.

## Goal

> The main consequence of not pausing a big job, or of being too late while trying to do so, is that we end up in a long period of time where the user cannot use Claude Code at all, even if it's for a very urgent work that would not require a lot of tokens (like answering an important email). (Jean, 2026-11-11)

## Never locked out

| # | Requirement |
|---|---|
| R30 | Jean can always do small urgent work: no big job takes a window or the week to its limit long before its reset. |
| R31 | The week is protected as well as the window; a lockout of the week, which can last days, weighs more than one of a window. |
| R32 | Small urgent work always goes through, even near the limit: a short question in an interactive session is never paused or refused. |
| R33 | A lockout that would cost Jean nothing does not cause a pause: one of a few minutes just before the reset, or one at an hour when Jean does not use Claude. |
| R34 | Use outside Claude Code (claude.ai, the phone apps, cloud sessions) is counted when judging whether a lockout is ahead, and is never paused. |
| R35 | Work on the Mac and on the VM is protected alike, since both use the same account. |

## Pausing only when it is worth it

| # | Requirement |
|---|---|
| R36 | A big job that can finish with a little more quota is left to finish rather than paused (Jean's example: 1 % more and it is done). |
| R37 | A big job that would hit the limit anyway is paused before the limit, while Jean's reserve is still whole. |
| R38 | When to pause follows from how much worse Jean finds a lockout than a delayed job, not from a fixed percentage. |
| R39 | When several jobs could be paused, the least urgent goes first, and the work the maximizer started goes before any of Jean's. |
| R40 | When launching work, Jean can say it is a big job that may wait, or urgent work that must not be paused; work Jean said nothing about is judged by how fast it uses quota. |
| R41 | The protector never pauses, and never lets a big job run on, because of a reading that is too old to trust; when it cannot see the quota, Jean is told. |

## Pausing and resuming without loss

| # | Requirement |
|---|---|
| R42 | A paused job loses nothing: neither its own work nor the work of its subagents. |
| R43 | A paused job resumes by itself after the reset, without Jean doing anything. |
| R44 | Paused jobs resume one after another, the most urgent first, so that resuming never causes the next lockout; none is resumed into a week that is itself close to its limit. |

## Seeing and deciding

| # | Requirement |
|---|---|
| R45 | Jean sees, where Jean is working, which job is paused, why, and when it resumes. |
| R46 | Jean can tell a paused job to go on anyway, or to resume now. |
| R47 | For any pause, or any decision not to pause, Jean can see why, in one place. |

## Secondary (nice to have, later)

| # | Requirement |
|---|---|
| R48 | The hours when Jean uses Claude are learned, not set by hand (R33). |
| R49 | Codex sessions are protected the same way. |

## Out of scope

| What | Where it goes instead |
|---|---|
| Spending quota that would be lost | the maximizer ([`../maximizer/`](../maximizer/)) |
| Buying extra usage, or switching plans | Jean |
| Pausing claude.ai, the phone apps or cloud sessions | — (counted, never touched: R34) |
| Telling Jean through the phone's ntfy topic | never: it is for defcon-alert alarms only |

## Decided questions

| Question | Answer |
|---|---|
| Which meters? | the window and the week (Jean, 2026-11-11) |
| How much worse is an hour of lockout, when Jean needs Claude, than an hour of delay to a big job? (sets R38) | 10× to start (Jean, 2026-11-16) |
| How much quota is kept for small urgent work (the reserve)? | 5 % of the window and 5 % of the week to start (Jean, 2026-11-16) |
| How does the protector know a big job? (R40) | both: Jean says so at launch, and otherwise it is detected by its burn rate (Jean, 2026-11-16) |
| Where is Jean told? (R45) | on the session's own terminal pane (agent-notify) and in the status line (Jean, 2026-11-16) |
| Can a job be paused for hours without losing anything? | yes, tested: a hook held a session and its subagent for 5 h 05 min, then the work went on (2026-11-11, [`../doc/prior_work.md`](../doc/prior_work.md) §2) |
