#!/usr/bin/env python3
"""Adds or removes agent-quota's hook group in ~/.claude/settings.json, touching nothing else.

`hooks` is shared (skill config-ownership): ours is the PreToolUse group whose command contains MARK; `set` replaces it
(a re-run never adds a second one), `unset` removes it. Origin: layer-firewall hooks/merge_claude_hooks.py.
The group matches every tool, in subagents too, so that a freeze reaches all the work of a session (protector/DESIGN.md).
`timeout` 21600 s (6 h) covers any window: a 5 h 05 min hold was tested (doc/prior_work.md §2). `onFailure` is left
unset on purpose: the hook fails open (protector/DESIGN.md §8).
Usage: merge_claude_hooks.py set|unset. Env: CLAUDE_SETTINGS (default ~/.claude/settings.json). Prints changed, unchanged or absent.
"""
import json
import os
import sys
from pathlib import Path

MARK = "opt/agent-quota/bin/agent-quota"
COMMAND = '[ ! -f "$HOME/opt/agent-quota/bin/agent-quota" ] || python3 -I "$HOME/opt/agent-quota/bin/agent-quota" hook'
TIMEOUT_S = 21600

f = Path(os.environ.get("CLAUDE_SETTINGS") or Path.home() / ".claude" / "settings.json").resolve()  # a link (account b's settings.json -> ../settings.json): write its target, never replace the link (2026-11-21)
mode = sys.argv[1]
d = {}
if f.exists():
    d = json.loads(f.read_text())
elif mode == "unset":
    print("absent")
    sys.exit(0)


def ours(g):
    return isinstance(g, dict) and any(MARK in str(h.get("command", "")) for h in g.get("hooks") or [] if isinstance(h, dict))


d_hooks = dict(d.get("hooks") or {})
l = [g for g in d_hooks.get("PreToolUse") or [] if not ours(g)]
if mode == "set":
    l.append({"matcher": "*", "hooks": [{"type": "command", "command": COMMAND, "timeout": TIMEOUT_S}]})
d_hooks["PreToolUse"] = l
if not l:  # (an event left with no group is not written)
    del d_hooks["PreToolUse"]
d_new = {**d, "hooks": d_hooks}
if not d_hooks:
    del d_new["hooks"]
if d_new == d:
    print("unchanged")
else:
    tmp = f.with_suffix(".json.tmp")  # temp file + rename: a Claude Code starting meanwhile never reads half a file
    tmp.write_text(json.dumps(d_new, indent=2) + "\n")
    tmp.replace(f)
    print("changed")
