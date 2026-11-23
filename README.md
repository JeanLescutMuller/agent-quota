# agent-quota

**Stop hitting Claude's usage limits by surprise, and stop leaving paid quota unused: a protector pauses big jobs before a lockout, a maximizer spends spare weekly quota. For Claude Code subscribers who run long or many sessions.**

Quota management for Jean's Claude subscription, in two halves that never act at the same time. **State (2026-11-16): the protector v1 is built and runs on the Mac in `observe` mode (it decides and logs, holds nothing); the maximizer is designed, not built.**

```
bash install.sh            # deploy (idempotent); uninstall.sh undoes it
agent-quota status         # meters, who acts, each session and its decision
agent-quota mode on        # let the protector freeze big jobs (default: observe)
agent-quota go-on <id>     # never freeze this session until its window resets
agent-quota resume-now <id>
```

```
                     the tracker (agent-tracker)
             window %, week %, resets, $ and tokens per session
                                  │
                      projected % at each reset
                                  │
   window (5 h)   0 % ────────── normal ──────────┤─ lockout ahead ─ 100 %
   week (7 days)  0 % ─ spare quota ─┤─ normal ───┤─ lockout ahead ─ 100 %
                           │                              │
                           ▼                              ▼
                      maximizer/                     protector/
            week only: spends the quota      window and week: pauses big
            the week can never use, on       jobs, so Jean always keeps
            optional agents' tasks           quota for small urgent work
            (launched by the tasks repo)
```

| Half | State | Read first |
|---|---|---|
| protector | considerations: scenarios, risks, costs | [`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md) |
| maximizer | design agreed in part (moved from `tasks`, 2026-11-11) | [`maximizer/DESIGN.md`](maximizer/DESIGN.md) |
| both | how they stay apart | [`CONSIDERATIONS.md`](CONSIDERATIONS.md), [`REQUIREMENTS.md`](REQUIREMENTS.md) |
| what to build on | Jean's repos and tools online, 2026-11-11 | [`doc/prior_work.md`](doc/prior_work.md) |

## See also: several Claude accounts

Several Claude accounts on one machine: the overview (why, designs, how to use it, every piece and where it lives) is `/Users/jeanlescut/dev/infra/my-setup/doc/claude_accounts.html`.
