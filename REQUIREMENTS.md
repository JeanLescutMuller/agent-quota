# Requirements — agent-quota (both halves)

From Jean's point of view only: the benefit, never the mechanism. Words: [`AGENTS.md`](AGENTS.md) § Vocabulary. Each half's own requirements: [`maximizer/REQUIREMENTS.md`](maximizer/REQUIREMENTS.md); the protector's are not written yet ([`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md) first).

## Goal

> I want a project for quota management, with two halves: one for quota protection and one for the opposite, quota maximization. They should fire off in situations that do not overlap, with clear checks that make it impossible for them to fire at the same time. (Jean, 2026-11-11)

## Both halves

| # | Requirement |
|---|---|
| R1 | The protector and the maximizer never act at the same time, and anyone can see which check keeps them apart. |
| R2 | Work the maximizer started never causes the protector to act: what is spent from spare quota never puts Jean in a lockout. |
| R3 | Jean can switch each half off alone, without touching the other. |

## Decided questions

| Question | Answer |
|---|---|
| One project or two? | one project, two halves (Jean, 2026-11-11) |
| Where does the maximizer live? | here, moved from the `tasks` repo; `tasks` keeps launching the tasks (Jean, 2026-11-11) |
