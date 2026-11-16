#!/usr/bin/env bash
# Deploys agent-quota. Idempotent: safe to re-run at any time.
#   code     → ~/opt/agent-quota/{src,bin,tools}   (read-only copies of this repo's)
#   state    → ~/opt/agent-quota/state/             (kept across installs; mode starts as `observe`)
#   command  → ~/.local/bin/agent-quota             (link)
#   hook     → ~/.claude/settings.json, one PreToolUse group (tools/merge_claude_hooks.py; skill config-ownership)
# Reads nothing but this repo. Undo: uninstall.sh.
set -euo pipefail
REPO=$(cd "$(dirname "$0")" && pwd)
OPT="$HOME/opt/agent-quota"
ok() { printf '  ok   %s\n' "$1"; }

mkdir -p "$OPT/state" "$HOME/.local/bin"
for d in src bin tools; do
  [[ -d $OPT/$d ]] && chmod -R u+w "$OPT/$d" && rm -rf "${OPT:?}/$d"
  cp -R "$REPO/$d" "$OPT/$d"
  find "$OPT/$d" -name __pycache__ -prune -exec rm -rf {} +
  chmod -R a-w "$OPT/$d"
done
ok "code → $OPT/{src,bin,tools}"
[[ -f $OPT/state/mode ]] || { echo observe > "$OPT/state/mode"; ok "mode: observe (decides and logs, never holds)"; }
ln -sfn "$OPT/bin/agent-quota" "$HOME/.local/bin/agent-quota" && ok "~/.local/bin/agent-quota"
r=$(python3 "$OPT/tools/merge_claude_hooks.py" set) && ok "~/.claude/settings.json hooks: $r"
printf '  mode now: %s · agent-quota status\n' "$(cat "$OPT/state/mode")"
