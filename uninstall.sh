#!/usr/bin/env bash
# Removes what install.sh deployed: the hook group, the command link, the code copies. Keeps ~/opt/agent-quota/state/.
set -euo pipefail
OPT="$HOME/opt/agent-quota"
[[ -f $OPT/tools/merge_claude_hooks.py ]] && printf '  hooks: %s\n' "$(python3 "$OPT/tools/merge_claude_hooks.py" unset)"
[[ -L $HOME/.local/bin/agent-quota ]] && rm "$HOME/.local/bin/agent-quota" && echo "  link removed"
for d in src bin tools; do
  [[ -d $OPT/$d ]] && chmod -R u+w "$OPT/$d" && rm -rf "${OPT:?}/$d"
done
echo "  code removed; state kept in $OPT/state"
