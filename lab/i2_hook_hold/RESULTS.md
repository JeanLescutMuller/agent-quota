# I2 results: can a PreToolUse hook freeze a session?

The first run (2026-11-11, `run.sh`, run `runs/20261111T152225Z/`) is summarised in [`doc/prior_work.md`](../../doc/prior_work.md) §2, row I2: a 5 h 05 min hold works in the main agent and in a foreground subagent; at the hook's `timeout` the hook gets SIGTERM, and `onFailure:"block"` then blocks the call.

## 2026-11-16: background subagent, two holds, release file, interactive session

Claude Code 2.1.325, Haiku, on the MacBook. Hook: `hold_release.sh` (a copy of `hold.sh` whose hold also ends when `<dir>/release_main` or `<dir>/release_sub` appears, checked every 5 s). Scripts and runs:

| Script | Run (summary) | Sessions |
|---|---|---|
| `run_more.sh` | `runs/20261116T174203Z_more/summary.txt` | T1–T3, `claude -p`, 3 at once, $0.03 in all |
| `run_tui.sh` (under `agent-tracker/tests/run_with_test_tmux.sh`: every tmux call on a throwaway socket) | `runs/20261116T174511Z_tui/summary.txt`, `screens/` | U1–U3, interactive `claude` in tmux, 3 at once |

| Test | Result | Evidence (Unix seconds) |
|---|---|---|
| T1 background subagent held 120 s (scope sub) | **hold kept**; the main agent went on: its 3 Bash calls passed unheld (markers 951, 973, 994); then it ended its turn and made **no request** until the subagent's call ran (1050); `claude -p` stayed alive, started a new turn on the subagent's result and replied DONE | hook: hold_start 930 → hold_end 1050 (timeout); END "still running" then END "subagent replied DONE" |
| T2 main + background subagent held at once (scope all), released at different times | **both kept, each released alone**: sub released 990 → its call ran 996; the sub's result arrived (997) while the main call was still held; it waited, no request, until the main release 1079 → call ran 1079 | hook: main 928–1079, sub 929–994, both reason=release |
| T3 release file 30 s into a 300 s hold | **call ran 6 s after the file** (file 957 → hold_end 961 → marker 963) | 5 s poll + ~2 s; DONE |
| U1 TUI held 120 s, text typed during the hold | **hold kept, TUI responsive**: spinner and timer run ("running PreToolUse hooks… 3/4 · 32s"), typed text shows in the input box; the call ran at the end (marker 1247), DONE | `screens/U1_type_*` |
| U2 TUI, a message typed + Enter during the hold | **hold kept**: the message is queued ("Press up to edit queued messages", "ctrl+x ctrl+s to send now"); the call ran at the end (1247), then the queued message was answered ("Four") | `screens/U2_submit_*` |
| U3 TUI, Esc during the hold | **Esc ends the freeze**: hook SIGTERM within 1 s (1151 → KILLED 1152), the call is **not** run ("Interrupted · What should Claude do instead?"), session alive and idle | `screens/U3_escape_*` |
| Mac sleep during a hold | **not tested** (see below) | — |

Not tested: "ctrl+x ctrl+s to send now" on a queued message (likely the cancel of #104363), a hold longer than 300 s in the TUI.

### Mac sleep: what is known, untested

- `pmset -g`: `sleep 0 (sleep prevented by caffeinate…)`: two other `claude` processes each had a child `caffeinate -i -t 300` (renewed while they work). The two T1/T2 `claude -p` sessions, checked once at 17:43 UTC (one held, one running a Bash call), had **no** `caffeinate` child. So what keeps the Mac awake during a freeze is unknown.
- `pmset -g log` (since 2026-11-09): 20 `Idle Sleep`, 4 `Clamshell Sleep`, ~230 maintenance/dark-wake cycles. The 5 h hold of 2026-11-11 (15:22–20:27 UTC) crossed **no** sleep.
- So a frozen session may let the Mac idle-sleep; whether the hook's `sleep`/poll and Claude Code's hook timer survive it is unknown. A protector that keeps the Mac awake would need its own `caffeinate`.

### What it means for the protector's freeze

- A hook hold freezes the main agent, foreground and background subagents, together or one by one, at zero tokens while held (no request during the hold).
- A release file works: `resume-now` takes ≤ poll interval + ~2 s (5 s poll → 6 s).
- Interactive sessions: freezing is safe for Jean's typing (messages queue), but **Esc cancels the freeze and the held call** (the turn stops; nothing runs). The protector must expect that and re-freeze at the next call.
