# Considerations — agent-quota (both halves)

What might matter for the project as a whole: the two halves and how they stay apart. **This file states no design choice, on purpose.** Each half's own points: [`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md), [`maximizer/CONSIDERATIONS.md`](maximizer/CONSIDERATIONS.md). Words: [`AGENTS.md`](AGENTS.md) § Vocabulary.

## 1. The two halves are the two ends of one question

Both halves ask the same question of the same numbers: **where will the quota % be at the reset, at the current burn rate?** The protector asks it of both meters, the window and the week; **the maximizer asks it of the week only** (Jean, 2026-11-11).

```
projected % at the reset, each meter on its own

window (5 h)   0 % ───────────── normal ─────────────┤── lockout ahead ── 100 %
                                (nobody)                   protector

week (7 days)  0 % ── spare quota ──┤──── normal ────┤── lockout ahead ── 100 %
                       maximizer        (nobody)           protector
```

- **Quota left in a window is not lost.** A window that ends at 30 % leaves quota the next windows can still use, as long as the week is the limit. Only quota the week cannot use before its reset is lost for good: that, and only that, is spare quota. So a window projected to end low never starts the maximizer by itself.
- **Which half may act** (R1), from the two meters together:

| Window (5 h) | Week (7 days) | Who acts |
|---|---|---|
| lockout ahead | any | protector |
| any | lockout ahead | protector |
| normal | spare quota | maximizer |
| normal | normal | nobody |

| Half | Meters | Acts when | Worst mistake |
|---|---|---|---|
| maximizer | the week only | the week will end with quota it can never use (spare quota), and no meter has lockout ahead | spending quota Jean then needs |
| protector | the window and the week | either will reach 100 % long before its reset (lockout ahead) | a lockout while Jean has small urgent work |

## 2. Keeping them apart (R1, R2)

- **One shared reading, three states.** If both halves read the same numbers through one function that returns exactly one of `spare quota` / `normal` / `lockout ahead`, they cannot both act: the states exclude each other by construction.
- **A gap between the two ends.** Without one, a ping-pong is possible: the maximizer launches tasks, the projection crosses into lockout ahead, the protector pauses them, the projection falls, the maximizer launches again. Worked example: the maximizer may launch only if the projection *with its launch* stays at least G % below the protector's line. With G = 10 % and the protector's line at 95 %, a launch that would project 88 % is allowed; one that would project 90 % is not.
- **The window and the week can disagree.** The week may hold spare quota while the current window has lockout ahead, e.g. Monday afternoon with a big job running. The table of §1 settles it: lockout ahead on either meter wins, and the maximizer waits.
- **The maximizer already carries a protector-like check**: "skip if the 5-hour window is above 90 %" ([`maximizer/DESIGN.md`](maximizer/DESIGN.md) §5). So does the `tasks` auto-launch: launches wait above 90 % (`/Users/jeanlescut/dev/tasks/src/launch/step.py`, `QUOTA_MAX`). Both should become the shared check.

## 3. Shared inputs

| Input | From | State (2026-11-11) |
|---|---|---|
| window and week %, their resets | the tracker: `/Users/jeanlescut/opt/agent-tracker/data/claude/quota_latest.json` | exists; read 2026-11-11 14:14 UTC: window 32 %, week 72 % |
| $ and tokens per session, per folder | the tracker's databases (`FOR_READERS.md`) | exists |
| B, B_week | measured by the maximizer (`maximizer/DESIGN.md` §6) | measured once, 2026-10-12 |

- **The `tasks` quota guard is not a safe base.** It reads the tracker's new path since 2026-11-07 (`tasks` commit `bfb3cbb`; its `doc/task_manager.md` §4.2 still names the old one), but it opens the database with `mode=ro` (the tracker's rule 2 says macOS intermittently refuses it), lets launches through when the database is missing or unreadable, and checks neither the reading's age nor the week (`/Users/jeanlescut/dev/tasks/src/launch/step.py`, checked 2026-11-11). One shared reader, failing safe, avoids this.
- **Mac and VM share one account.** Both machines burn the same windows; a half that runs on one machine only sees the other's sessions through the tracker.
