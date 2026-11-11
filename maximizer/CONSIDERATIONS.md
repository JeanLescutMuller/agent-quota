# Considerations — the maximizer

Moved from the `tasks` repo (`design/CONSIDERATIONS.md` §7) on 2026-11-11. **This file states no design choice, on purpose.** The open points of the design are in [`DESIGN.md`](DESIGN.md) (Open points). Beyond them:

- **The legacy quota maximizer's numbers come from Pro.** Its 42-day replay, its bench and the share of each window it kept for Jean were measured on Pro; on Max 5x only one full week was measured. Every number is re-measured once the step runs.
- **The tracker expects this step**: its `FOR_READERS.md` lists "a future quota maximizer" as a reader; a change to the tracker's tables reaches this step.
- **The `tasks` repo still owns the launch.** The maximizer decides how much spare quota there is and when; the claim and the launcher stay in `tasks` (step 5 of `task-manager` in its design). Where the gate's code runs (a step of `task-manager`, or a job of its own here) is open.
