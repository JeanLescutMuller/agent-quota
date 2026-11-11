# agent-quota

Quota management for Jean's Claude subscription, in two halves that never act at the same time. **Design stage: nothing is built yet.**

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
| tools found online | 2026-11-11 | [`doc/existing_tools.md`](doc/existing_tools.md) |
