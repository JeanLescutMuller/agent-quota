# Existing tools (found online, 2026-11-11)

Public tools close to either half, found by web search on 2026-11-11. **Not verified**: described from their listings and READMEs as shown by search, no code read, no maintenance status checked.

## Close to the protector

| Tool | Where it reads the quota % | What it does above its threshold | Default |
|---|---|---|---|
| [Vrakoss/claude-usage-guard](https://github.com/Vrakoss/claude-usage-guard) | Anthropic's usage endpoint (OAuth) | blocks, then waits until the reset | fixed |
| [codenote-net/cc-usage-guard](https://github.com/codenote-net/cc-usage-guard) ([write-up](https://codenote.net/en/posts/cc-usage-guard-claude-code-rate-limits-stop-hook/)) | status line → a file | stops the session (PreToolUse, UserPromptSubmit) | 90 % |
| [Camellia-inc/usage-guard](https://github.com/Camellia-inc/usage-guard) | status line | refuses tools and prompts | 90 % |
| [eltonylfgi-blip/claude-code-usage-guard](https://github.com/eltonylfgi-blip/claude-code-usage-guard/blob/main/README.md) | ? | blocks | ? |
| [limit-usage (pokutuna)](https://claudemarketplaces.com/plugins/pokutuna-claude-plugins/limit-usage), [claude-limit-guard](https://awesome.ecosyste.ms/projects/github.com%2Ffunhunter7%2Fclaude-limit-guard), [rate-limit-guard](https://www.claudepluginhub.com/plugins/willyt3hwhale-rate-limit-guard) | status line | refuse tool calls | 90–95 % |
| [claude-session-budget](https://pypi.org/project/claude-session-budget/1.1.1/) | an estimate from local session files | blocks, or waits until the % falls | 93 % |
| [mthc](https://www.pkgstats.com/pkg:@jinba1/mthc) | hooks | 85 %: asks Claude to wrap up; then blocks and writes a handoff report | 85 % |
| [Dede98/claude-usage](https://github.com/Dede98/claude-usage) `guard --pid` | its own usage reading | pauses or kills a given process | 80 % |
| [jarredkenny/clauditor](https://github.yezi957.workers.dev/jarredkenny/clauditor) | — (no quota reading) | `SIGSTOP` / `SIGCONT` on a session and its children | — |
| [TakalaWang/claude-quota-guard](https://github.com/TakalaWang/claude-quota-guard) | — | blocks a project past its share of the week, or its $ | — |
| [budget-guard (claude-mods)](https://github.com/Arunjay4213/claude-mods/tree/main/plugins/budget-guard) | — | blocks a session past a $ limit | — |

## Resuming after a reset

| Tool | How |
|---|---|
| [claude-powernap](https://pypi.org/project/claude-powernap/0.3.1/), [wakey-claude](https://dev.to/maxmoffa/wakey-claude-surviving-the-claude-code-5-hour-usage-window-5h95) | checkpoint before the limit, wake up at the reset |
| [quotawake](https://notes.dsebastien.net/30+Areas/33+Permanent+notes/33.02+Content/quotawake) | reads the reset time, sets an alarm, continues in a new session |
| [sleepless-agent](https://context-machine-lab.github.io/sleepless-agent/concepts/pro-plan-management) | a 24/7 agent runner that plans its work around the windows |
| [claude-auto-retry](https://www.pkgstats.com/pkg:claude-auto-retry), [Smart Resume](https://dev.to/karthikeyan_natarajan_1cb/i-built-a-shell-wrapper-that-makes-claude-code-auto-resume-after-rate-limits-2lje) | watch the terminal, type "continue" after the reset |
| Claude Code `/config` → "Continue automatically at usage limit" | built in; [reported](https://claudeissues.com/issue/92418-bug-auto-continue-disabled-after-five-hour-rate-limit-reset-with-multiple-sessio) not to resume with several sessions open |

## Facts from these sources

- The quota % reaches a session only through the status line's JSON (`rate_limits.five_hour.used_percentage`, `rate_limits.seven_day.…`); hook inputs do not carry it. With an API key it is absent.
- Feature requests to Anthropic ask for the same thing: [a reserve for graceful wrap-up](https://claudeissues.com/issue/42935-feature-request-reserve-capacity-for-graceful-wrap-up-low-power-mode-near-limit), [a soft ceiling with checkpoint](https://claudeissues.com/issue/63969-client-side-soft-session-ceiling-with-graceful-checkpoint-for-autonomous-subagen), [usage exposed to the model](https://claudeissues.com/issue/65524-expose-current-usage-limit-state-to-the-model-self-pacing-for-long-autonomous-ru).
- Codex: no such tool and no setting found, only [feature requests](https://community.openai.com/t/feature-request-user-configurable-usage-limit-warning-and-safe-pause-for-codex-work/1398420).
