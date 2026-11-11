# agent-quota

Quota management for Jean's Claude subscription, in two halves that never act at the same time. **Design stage: nothing is built yet.**

```
                        the tracker (agent-tracker)
                window %, week %, resets, $ and tokens per session
                                    │
                        projected % at the reset
                                    │
        ┌───────────────────────────┼────────────────────────────┐
   spare quota                   normal                    lockout ahead
        │                     (nobody acts)                      │
        ▼                                                        ▼
  maximizer/                                               protector/
  spends quota that would be lost                          pauses big jobs, so Jean
  on optional agents' tasks                                always keeps quota for
  (launched by the tasks repo)                             small urgent work
```

| Half | State | Read first |
|---|---|---|
| protector | considerations: scenarios, risks, costs | [`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md) |
| maximizer | design agreed in part (moved from `tasks`, 2026-11-11) | [`maximizer/DESIGN.md`](maximizer/DESIGN.md) |
| both | how they stay apart | [`CONSIDERATIONS.md`](CONSIDERATIONS.md), [`REQUIREMENTS.md`](REQUIREMENTS.md) |
| tools found online | 2026-11-11 | [`doc/existing_tools.md`](doc/existing_tools.md) |
