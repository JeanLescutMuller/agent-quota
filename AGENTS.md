# agent-quota

**Quota management for Jean's Claude subscription, in two halves that never act at the same time: the protector pauses big jobs so Jean is never in a lockout; the maximizer spends spare quota before it is lost.**

## Rules

- **Design stage: nothing is built.** Each half has its own design files: [`protector/`](protector/), [`maximizer/`](maximizer/). Shared points: [`CONSIDERATIONS.md`](CONSIDERATIONS.md), [`REQUIREMENTS.md`](REQUIREMENTS.md).
- **The two halves never act at the same time** (R1): any rule that lets one act must say which check makes the other impossible. → [`CONSIDERATIONS.md`](CONSIDERATIONS.md) §2
- **Read the quota only through agent-tracker** (`/Users/jeanlescut/dev/agent-tracker/FOR_READERS.md`): never write its files; a quota % is account-wide, never a session's.
- **The maximizer's launches go through the `tasks` repo's launcher** (`/Users/jeanlescut/dev/tasks`); never a second launcher here.

## Vocabulary

The only words for these concepts, in every file and when talking to Jean. A new word is added here first, with Jean's agreement.

| Word | Means | Never say |
|---|---|---|
| **quota %** | the account's meter, in % of a window or of the week (agent-tracker's `five_hour` / `seven_day` `used_percentage`) | usage, consumption |
| **window** | a Claude 5-hour quota meter; it exists only once a request opens it | session, period, envelope, interval |
| **week** | the 7-day quota meter; Claude's resets Monday 19:00 UTC | — |
| **reset** | when a window or the week ends and its % returns to 0 | renewal |
| **lockout** | a time when Jean cannot use Claude Code at all, because a window or the week is at 100 %, until its reset | outage, block |
| **protector** | the half that pauses big jobs so that Jean is never in a lockout (quota protection) | guard, shield |
| **maximizer** | the half that spends spare quota on optional agents' work (quota maximization) | spender, harvester |
| **lockout ahead** | at the current burn rate, a window or the week reaches 100 % before its reset: only the protector may act | scarcity, shortage |
| **spare quota** | quota that would be lost at the weekly reset even if every window left this week were used in full: only the maximizer may act | free quota, leftover, extra |
| **big job** | a session or process that uses a large share of a window: a long run, many subagents | long process, heavy session |
| **small urgent work** | a short piece of work Jean needs now (answering an important email) | — |
| **interactive session** | a Claude Code session Jean types in | — |
| **reserve** | the % of a window or of the week kept for Jean's small urgent work | buffer, margin |
| **pause** | stopping a big job before the limit, to resume it after the reset | halt, kill |
| **checkpoint** | the agent writes where its work stands (its subagents' too) to a file, then stops | snapshot, save |
| **freeze** | a pause where the session stays alive, held before its next tool call | suspend |
| **resume** | continuing paused work after the reset | restart |
| **burn rate** | how fast quota is used; the unit is always stated (% of a window per minute, $ per hour) | speed |
| **$** | Claude Code's own dollar figure (tokens × list price), never a bill | cost, price |
| **B** / **B_week** | the $ one full window / one full week holds, measured ($194 / $1,469 on Max 5x, 2026-10-12) | budget, capacity |
| **unit** | one full window's $ (= B), for display only | — |
| **unknown** | quota the meter moved that no machine's records explain (claude.ai, the phone apps, cloud sessions) | unallocated |
| **subscription** | Claude, or ChatGPT/Codex: one quota meter each | agent |
| **the tracker** | agent-tracker (`/Users/jeanlescut/dev/agent-tracker`), which records the quota readings and usage | agent-usage-tracker (old name) |
| **Category 1 / 3 / 4** | the tracker's words: quota readings / 5-minute slots of $ and tokens / what a reader computes from them | — |

## Where to look

| | |
|---|---|
| what the protector must weigh: scenarios, risks, costs | [`protector/CONSIDERATIONS.md`](protector/CONSIDERATIONS.md) |
| the maximizer's design (moved from `tasks` on 2026-11-11) | [`maximizer/DESIGN.md`](maximizer/DESIGN.md) |
| the existing tools found online (2026-11-11) | [`doc/existing_tools.md`](doc/existing_tools.md) |
