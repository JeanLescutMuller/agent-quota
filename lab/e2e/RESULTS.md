# End-to-end test of the agent-quota hook — results

`run_e2e.sh`, run 2026-11-16 17:55 UTC on the Mac (Claude Code 2.1.322, `claude -p`, Haiku), with the repo's `bin/agent-quota hook` as the PreToolUse hook (matcher `*`) and a freeze forced into `decisions.json` after the session's first call.

| Test | Mode | What happened | Verdict |
|---|---|---|---|
| E1_on | on | the 2nd Bash call held 17:55:50 → 17:56:26 (36 s); `agent-quota resume-now` released it at once (`why='override'`); the call ran within 1 s; the session ended DONE | pass |
| E2_observe | observe | the same forced freeze: the 2nd call ran at once, never held | pass |
| E3_sub | on | the freeze caught the main agent's next tool call, the Agent call that would start the subagent: held 39 s, released by `resume-now`; the subagent then ran and answered DONE | pass (a freeze stops a session at its next call, whoever makes it; a subagent already running is held at its own next call: `../i2_hook_hold/RESULTS.md`) |

No hook errors in any test.
