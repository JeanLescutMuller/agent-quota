# Prior work: what agent-quota can build on

What exists, inside Jean's own repos and online, for the protector and the maximizer, and what to take from each. Researched on 2026-11-11 (Claude Code 2.1.322) by four agents that read the code of every tool from shallow clones and ran none of it. **V** = seen in the code (or, for Claude Code, in Jean's own transcripts); **R** = only stated in a README, the docs or an issue. Stars and last push as of 2026-11-11. Words: [`../AGENTS.md`](../AGENTS.md) § Vocabulary.

## 1. The verdict

**No project is a starting point as a whole: nothing reads the quota %, pauses cleanly, and resumes subagent work; and nothing spends only the week's spare quota.** agent-quota starts new, and takes these pieces:

| Building block | Best source | License | Take |
|---|---|---|---|
| reading the quota % | **the tracker** (`quota_latest.json`, ≤ 3–9 min old; Jean's own) | own | as-is |
| live burn rate per session, subagents included | **the tracker's `telemetry`** (written ≈ 4 s after each request; subagents under the parent's session id) | own | as-is |
| forecast of the whole meter | Jean's legacy `s2_predict.py` (recent rate, measured best) + rbartoli's projected full time + pacer's guards | own / MIT / MIT | adapt |
| decision line from costs, not a fixed 95 % | Jean's legacy forecasting lab: q = C_lockout / (C_lockout + C_pause) | own | the method |
| freeze | willyt3hwhale's sleeping PreToolUse hook (`timeout` 18000 s) + `onFailure:"block"` (docs) | none: idea only | rebuild, **test first** |
| subagents wind down cleanly | Vrakoss: `agent_id` → "return a resume brief", hand-back tools left outside the gate | MIT | copy |
| checkpoint in two stages | mthc: a soft wrap-up prompt, then a hard deny where the hook writes the handoff file itself | MIT | copy the idea |
| resuming cut subagents | Claude Code itself: `SendMessage` to the subagent's id (docs; user-verified [#94222](https://github.com/anthropics/claude-code/issues/94222)) | — | keep a list of ids |
| resuming a session | quotawake / powernap rules (`claude --resume <id> --bg`, never fork a live one) + Jean's `ares` | MIT / own | adapt |
| the maximizer's window arithmetic | Jean's legacy `s3_budget.py` (two limits, never multiplied; fill from the last window) | own | nearly as-is |
| $ per % of the week, measured continuously | ccpool `calib/compute.go` | MIT | copy the method |
| launch rules for spare quota | idlemax (fails closed, interactive hold, last 24 h rule) | MIT | copy the ideas |

## 2. Facts about Claude Code (answers to protector I1, I2, I6)

| # | Fact | Source |
|---|---|---|
| I1 | At the limit, a **foreground subagent** returns its partial text or fails with `Agent terminated early due to an API error`; a **background** one is marked failed, its last output passed to the parent | R: docs `sub-agents.md` |
| I1 | **A cut subagent can be continued**: `SendMessage` to its id once the limit clears. Explore and Plan agents have no id; after a restart the ids must have been written down; models tend to re-spawn instead (one user: 449 cut, 8 resumed) | R: docs; user-verified [#94222](https://github.com/anthropics/claude-code/issues/94222) |
| I1 | Bugs: a killed foreground subagent is reported "Done" ([#82829](https://github.com/anthropics/claude-code/issues/82829)); Workflow agents restarted from zero ([#91449](https://github.com/anthropics/claude-code/issues/91449); workflows pause at the limit since 2.1.271) | R: issues, changelog |
| I1 | The transcript records the limit as `error:"rate_limit"` with `quotaLimits:{resetsAt, rateLimitType}`; subagents' transcripts are `<project>/<session>/subagents/agent-<id>.jsonl` | **V**: Jean's transcripts |
| I2 | Hooks **fire inside subagents**, with `agent_id` and `agent_type` in the input | R: docs `hooks.md`; V: Vrakoss uses it |
| I2 | A command hook's `timeout` defaults to 600 s, **no maximum documented**; on timeout the tool **runs anyway**, unless the hook sets `onFailure:"block"` (2.1.295+) | R: docs |
| I2 | **Warning**: a hold that times out every 600 s and then lets the call through made background agents re-read their whole context each time: 53 M tokens, ≈ 14 % of a Max week, in 4 h ([#106385](https://github.com/anthropics/claude-code/issues/106385)). A message Jean types can cancel a hook in flight ([#104363](https://github.com/anthropics/claude-code/issues/104363)) | R: issues |
| I2 | **A hold of hours: untested anywhere.** A 20-minute test settles it | — |
| I2 | Mods (Claude Code's in-process hooks) have a 10 s limit that `$.clock.sleep` counts toward: **a mod cannot freeze** | R: mods reference |
| I2 | `defer` (a PreToolUse decision) ends a `claude -p` turn cleanly; `claude -p --resume` later runs the held tool; only with one tool call in the turn | R: docs |
| I6 | `autoContinueAtUsageLimit` (2.1.234+, on by default): an **interactive** session waits at the limit and continues at the reset. Not for `-p` or background sessions; not when the reset is > 24 h away (**so never for the week**); stops after 3 continuations; needs Enter after a sleep > 30 min; resumes the main agent only; never resumes with several sessions sharing a window ([#92418](https://github.com/anthropics/claude-code/issues/92418), open) | R: docs `interactive-mode.md`, issue |
| I6 | Near 95 %, Claude Code prints "Approaching your 5-hour usage limit — Claude will wrap up the current step", tells the model to start no subagents, then **parks the session with nothing to resume it**. Feature-flagged, no setting, not in the docs | R: observed by claude-auto-retry; announced on X 2026-09-25 per a secondary article |
| — | `StopFailure` (matcher `rate_limit`) fires when a turn ends on a limit; its input has no reset time (read it from the transcript); its output is ignored | R: docs |
| — | `/v1/messages` responses carry `anthropic-ratelimit-unified-{5h,7d}-utilization` and `-reset` headers | V: willyt3hwhale |
| — | The OAuth usage endpoint answers HTTP 429 when polled too often: ≥ 180 s apart | V: Usage-Monitor; the tracker measured ≈ 21 % of calls refused |
| — | A status line's `used_percentage` sometimes carries the reset timestamp instead of a % (bug #52326) | V: Usage-Monitor guards against it |
| — | `claude -p` never runs a status line, so its own use reaches a reading only through other sessions or the poller | V: idlemax |

## 3. Jean's own repos

| Repo | Gives the protector | Gives the maximizer | Take | Paths |
|---|---|---|---|---|
| **the legacy agent-quota-maximizer** (in `tasks` history: `git -C /Users/jeanlescut/dev/tasks show 8c0c9fc^:legacy/agent-quota-maximizer/…`) | the forecasting lab and its bench; "active in the last 30 min" as the signal Jean will need Claude | `s3_budget.py` (window arithmetic), `s2_predict.py`, the 42-day replay | adapt (standard library; 261 tests passed 2026-10-11; reads old CSVs) | `release/aqm/`, `lab/02_prediction/`, `lab/07_pipeline/pipeline_replay.py` |
| **agent-tracker** | `quota_latest.json`; per-session $ in `telemetry` (live); who runs where (`agent-tracker now --json`) | `latest`, `slots`, B and B_week (`adhoc_quotas_analysis/budgets.py`, a manual script) | as-is, read-only | `FOR_READERS.md` |
| **agent-resume** (`ares`) | builds `cd <dir> && claude --resume <uuid>` and types it into a tmux pane | — | adapt | `src/ares` (`tmux_plan`, `cmd_tmux`) |
| **agent-auto-close** | a clean close (safety checks, saves the pane's screen, SIGTERM, types the resume command); refuses busy sessions, which are the protector's targets | — | adapt | `src/agent-auto-close` |
| **agent-notify** | can show "paused" on a pane | — | adapt, small | README |
| **tasks** `src/launch/` | its runs are known big jobs (`runs.jsonl`: session, minutes, $); a kill path (killpg) | burn-rate samples; the launcher the maximizer uses | adapt | `step.py`, `launcher.py` |

**What the legacy forecasting lab found** (42 days, Pro, test split by calendar time; `design/02_prediction/DESIGN.md` §8):

| Method (forecast of Jean's own use to the window's end) | Cost per tick | vs recent rate |
|---|---|---|
| percentile per (state × clock band) | 6.96 | −1.1 % |
| **recent rate**: max(last 30 min, window average), × 1.5 (the built one) | **7.03** | — |
| gradient boosting, quantile loss | 7.06 | +0.4 % |
| hierarchical Gaussian | 7.52 | +6.9 % |
| best constant reserve | 9.62 | +36.8 % |
| do nothing | 27.76 | +295 % |

- **Any forecast beats none by ≈ 4×; choosing among them moves ≈ 1.5 %.** The winner flips with the ratio of the two costs (here quota taken from Jean was costed 10× wasted quota): agree the ratio with Jean, then the line follows.
- **"Active in the last 30 min" is the strongest signal**: chance Jean uses > 25 % of a window within 5 h: 52 % if active, 13 % if not.
- The forecast said 0 on 73.6 % of ticks, while use to the window's end then reached 26 % (90.9th percentile): a fixed floor is needed.

## 4. Tools online

| Tool | ★ | Last push | License | What it does | Take |
|---|---|---|---|---|---|
| [rbartoli/agent-usage-guard](https://github.com/rbartoli/agent-usage-guard) (mod) | 96 | 11-10 | MIT | burn rate over 10 min across sessions; projected full time, trusted only with ≥ 2 min span, ≥ 2 points, ≤ 1 h horizon (`core/agents.ts:239-267`); refuses new subagents, tools, prompts; refuses ScheduleWakeup/CronCreate at 95 %; a refusal ladder and fuse (`core/verdict.ts:72-105`). No pause, no resume | **the protector's projection and refusals** |
| [Vrakoss/claude-usage-guard](https://github.com/Vrakoss/claude-usage-guard) | 0 | 10-17 | MIT | OAuth endpoint; deny, then ScheduleWakeup chain to the reset; subagents (`agent_id`) return a resume brief (`scripts/usage-guard.mjs:805-837`); a latch against `/goal` re-driving a paused agent (:61-79) | **subagent wind-down** |
| [drpwchen/claude-pacer](https://github.com/drpwchen/claude-pacer) | 8 | 11-03 | MIT | projected = max(window average, recent least-squares); within 20 min of the reset every level drops one (= S4); the week ignored when it resets before the window ends (`usage_verdict.py:147-229`); readings > 15 min old ignored | **the rule's guards** |
| [willyt3hwhale/cc-limit-guard](https://github.com/willyt3hwhale/cc-limit-guard) | 4 | 02-05 | none | **the only freeze**: PreToolUse sleeps to the reset + 60 s, `timeout` 18000 (`rate_limit_guard.js:64-80`); reads the % with a 1-token Haiku call | idea only |
| [JinBa1/my-time-has-come](https://github.com/JinBa1/my-time-has-come) (mthc) | 4 | 06 | MIT | soft wrap-up prompt (PostToolBatch), then deny + a handoff file the hook writes; separate window/week lines 85/95, 90/98; a reading never goes down within a window (`internal/state/state.go:77-95`) | **checkpoint in two stages** |
| [asiagenawi/claude-powernap](https://github.com/asiagenawi/claude-powernap) | 9 | 10 | MIT | triggers at 90 % or when the burn rate projects the limit within 9 min; checks every 15 s above 90 %; checkpoint protocol for the model (`usage_check.py:24-53`); a watcher reopens a stranded session, `lsof` first so a live one is never forked (`fallback_watch.py:107-140`) | **resume safety, checkpoint prompt** |
| [kvistgaard/quotawake](https://github.com/kvistgaard/quotawake) | 4 | 10 | MIT | finds stranded sessions in transcripts; `claude --resume <id> --bg` after the reset; waits 10 min for the built-in continue first | resume rules |
| [saaranshM/unsnooze](https://github.com/saaranshM/unsnooze) | 229 | 11 | MIT | StopFailure + screen → types into the pane or `--resume` | resume, idea |
| [cheapestinference/claude-auto-retry](https://github.com/cheapestinference/claude-auto-retry) | 394 | 10 | MIT | types `continue` after the reset; documents the built-in 95 % wrap-up | facts |
| [jarredkenny/clauditor](https://github.com/jarredkenny/clauditor) | 6 | 02 | MIT | SIGSTOP / SIGCONT on a process tree, children first | idea (risky mid-request) |
| [funhunter7/claude-limit-guard](https://github.com/funhunter7/claude-limit-guard) | 0 | 11-04 | MIT | Stop hook blocks once per window → `.claude/RESUME.md`; SessionStart offers to resume | idea |
| [pokutuna limit-usage](https://claudemarketplaces.com/plugins/pokutuna-claude-plugins/limit-usage) (mod) | 3 | 11-09 | MIT | `turn.step` answers itself so no request is sent, in subagents too | idea |
| [claude-mods budget-guard](https://github.com/Arunjay4213/claude-mods/tree/main/plugins/budget-guard) (mod) | 11 | 10-16 | none | deny, then `$.turn.abort` (a refused model keeps trying other tools) | idea only |
| [codenote-net/cc-usage-guard](https://github.com/codenote-net/cc-usage-guard) | 0 | 11-08 | MIT | status line → one atomic file → a hook; fixed 90 % | small idea |
| [shirley-xue-2025/usage-guard](https://github.com/shirley-xue-2025/usage-guard) | 15 | 07-29 | MIT | polls more often as the % rises; a `valid_until` on its state | small idea |
| [eltonylfgi-blip/claude-code-usage-guard](https://github.com/eltonylfgi-blip/claude-code-usage-guard) | 4 | 11-11 | MIT | pace = used % − elapsed %, warn only | ignore |
| [Star001-KR/claude-session-budget](https://github.com/Star001-KR/claude-session-budget) | 8 | 05 | MIT | estimate from transcripts; a sleep hold that the 600 s default cuts; count usage once per `requestId` (3.3× double count otherwise) | one fact |
| [Dede98/claude-usage](https://github.com/Dede98/claude-usage) | 3 | 04 | MIT | SIGTERM above 80 %; refuses readings > 300 s old | ignore |
| MaxMoffa/wakey-claude, karthiknitt/smart_resume, terryso/claude-auto-resume, TakalaWang/claude-quota-guard | — | — | — | kill or block, then resume by hand or by re-running | ignore |
| **Maximizer side** | | | | | |
| [mrx-arafat/idlemax](https://github.com/mrx-arafat/idlemax) | 0 | 11-10 | MIT | spends quota before it resets with `claude -p` / `codex exec`: reserves 40 % window, 30 % week (15 % in the week's last 24 h); only in the last third of a window or < 24 h before the weekly reset; holds 30 min after Jean's last session activity; one job per window (stale reading after `claude -p`); fails closed; job sizes 3/8/20 % of a window. Not spare quota: below 70 % of the week it spends on any day | **launch rules** |
| [SeanLF/ccpool](https://github.com/SeanLF/ccpool) | 4 | 11-02 | MIT | $ per 1 % of the week from the last 3 weeks, weighted, regime change on 3× disagreement (`internal/calib/compute.go`); runway in **active hours** from Jean's weekday × hour profile; noise guards on the integer % (`internal/burn/burn.go:25-42`). Launches nothing | **the weekly forecast** |
| [Maciek-roboblog/Claude-Code-Usage-Monitor](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor) | 8.8 k | 07-05 | MIT | linear projection on the window; reading guards (`output/official.py:42-60`) | small ideas |
| [JuanjoFuchs/ccburn](https://github.com/JuanjoFuchs/ccburn) | 97 | 10-06 | MIT | least-squares slope of the % | small idea |
| [paperclip PR #14781](https://github.com/paperclipai/paperclip/pull/14781) | — | 11-11 | MIT | fewer agents at once when use runs ahead of an even pace | idea |
| ClaudeTuner (closed) | — | — | — | projection per active hour, learns sleep and weekday rhythm (−63 % overshoot) | idea (README only) |
| [context-machine-lab/sleepless-agent](https://github.com/context-machine-lab/sleepless-agent) | 840 | 03-29 | MIT | fixed 20 % day / 80 % night on the window only; its "predictor" exists in the docs only | ignore |
| [ccusage](https://github.com/ccusage/ccusage) | 19 k | 11-11 | MIT | the tracker already matches it | ignore |
| Claude Code scheduled tasks ([Routines](https://code.claude.com/docs/en/routines)) | — | — | — | schedule, GitHub event, or an API `POST /fire`; **no quota trigger** | a possible launch path |
| Codex | — | — | — | no tool and no setting found, only [feature requests](https://community.openai.com/t/feature-request-user-configurable-usage-limit-warning-and-safe-pause-for-codex-work/1398420) | — |

## 5. What nobody has: agent-quota's own part

- The two halves that never act together, from one reading of both meters.
- The worst-case form of spare quota, which counts the windows left this week (only the maximizer's design has it).
- Pausing **by how much a big job still needs and how urgent it is**, not by a fixed %.
- A freeze or checkpoint that keeps subagent work, **and** a resume of those subagents by id after the reset.
- The week's lockout: Claude Code's own auto-continue gives up beyond 24 h.

## 6. Corrections to this repo's other files

- `claude -p` **does** send telemetry now: 505 requests and $29.56 under entrypoint `sdk` in the last 7 days; only the `sdk-cli` and `sdk-py` slots still lack a $ (V, the tracker, 2026-11-11). [`../maximizer/DESIGN.md`](../maximizer/DESIGN.md) §6 and §11 say otherwise.
- The tracker's Mac slots arrive ≈ 24 min late: too slow for a live decision; the protector reads `telemetry`.
