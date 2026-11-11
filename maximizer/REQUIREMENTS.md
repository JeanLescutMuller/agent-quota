# Requirements — the maximizer

From Jean's point of view only. Moved from the `tasks` repo (`design/REQUIREMENTS.md`, "Phase 4 · quota maximizer") on 2026-11-11, numbers kept. The requirements shared with the protector: [`../REQUIREMENTS.md`](../REQUIREMENTS.md). Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary.

## Goal

The quota Jean pays for and does not use is spent on agents' tasks before it is lost ("use it or lose it"). (from the `tasks` goal)

## Requirements

| # | Requirement | State |
|---|---|---|
| R15b | Quota that would otherwise be lost at the reset (use it or lose it) is spent on undated agent tasks, never at the expense of Jean's own use or of due tasks. | to build |
| R15c | Spending it never blocks Jean's interactive work: agents spend as late as possible and leave most of every 5-hour window to Jean. Accepted: on a heavy last day of the week, the weekly limit can still stop Jean. | to build |
| R28 | Jean can switch the quota spending off, alone, without stopping the upkeep of the open tasks or the due tasks. | to build |
| R23 | For any decision to spend or not, Jean can see why, in one place. | to build |
| R24 | Jean can see where each window's and each week's quota went, in $: Jean's own use, production jobs, agent tasks, and what no machine saw (claude.ai, the phone, an untracked machine). | to build |
| R25 | After a subscription change (e.g. Pro → Max 5x), the conversions between quota %, $ and units re-learn by themselves, never mixing before and after. | to build |
