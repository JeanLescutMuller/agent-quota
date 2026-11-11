# Considerations — agent-quota (both halves)

What might matter for the project as a whole: the two halves and how they stay apart. **This file states no design choice, on purpose.** Each half's own points: [`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md), [`maximizer/CONSIDERATIONS.md`](maximizer/CONSIDERATIONS.md). Words: [`AGENTS.md`](AGENTS.md) § Vocabulary.

## 1. The two halves are the two ends of one question

Both halves ask the same question of the same numbers: **where will the quota % be at the reset, at the current burn rate?**

```
projected % at the reset
  0 %                                                         100 %
  ├──── spare quota ────┤──────── normal ────────┤── lockout ahead ──┤
     maximizer may act        nobody acts            protector may act
```

| Half | Acts when | Worst mistake |
|---|---|---|
| maximizer | the week will end with quota unused (spare quota) | spending quota Jean then needs |
| protector | a window or the week will reach 100 % long before its reset (lockout ahead) | a lockout while Jean has small urgent work |

## 2. Keeping them apart (R1, R2)

- **One shared reading, three states.** If both halves read the same numbers through one function that returns exactly one of `spare quota` / `normal` / `lockout ahead`, they cannot both act: the states exclude each other by construction.
- **A gap between the two ends.** Without one, a ping-pong is possible: the maximizer launches tasks, the projection crosses into lockout ahead, the protector pauses them, the projection falls, the maximizer launches again. Worked example: the maximizer may launch only if the projection *with its launch* stays at least G % below the protector's line. With G = 10 % and the protector's line at 95 %, a launch that would project 88 % is allowed; one that would project 90 % is not.
- **The windows and the week can disagree.** The week may hold spare quota (maximizer's side) while the current window has lockout ahead (protector's side), e.g. Monday afternoon with a big job running. The order of the checks must be decided: probably the protector's check first, on both meters.
- **The maximizer already carries a protector-like check**: "skip if the 5-hour window is above 90 %" ([`maximizer/DESIGN.md`](maximizer/DESIGN.md) §5). So does the `tasks` auto-launch: launches wait above 90 % (`/Users/jeanlescut/dev/tasks/src/launch/step.py`, `QUOTA_MAX`). Both should become the shared check.

## 3. Shared inputs

| Input | From | State (2026-11-11) |
|---|---|---|
| window and week %, their resets | the tracker: `/Users/jeanlescut/opt/agent-tracker/data/claude/quota_latest.json` | exists; read 2026-11-11 14:14 UTC: window 32 %, week 72 % |
| $ and tokens per session, per folder | the tracker's databases (`FOR_READERS.md`) | exists |
| B, B_week | measured by the maximizer (`maximizer/DESIGN.md` §6) | measured once, 2026-10-12 |

- **A stale path already broke a guard.** The `tasks` auto-launch reads `~/opt/agent-usage-tracker/data/claude/account_quotas.db`; the tracker was renamed agent-tracker on 2026-11-07 and that folder no longer exists (checked 2026-11-11), so its quota guard is skipped ("no quota database here"). One shared reader avoids this happening twice.
- **Mac and VM share one account.** Both machines burn the same windows; a half that runs on one machine only sees the other's sessions through the tracker.
