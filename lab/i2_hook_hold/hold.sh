#!/usr/bin/env bash
# PreToolUse hook for the I2 test: logs the call, then holds it for <hold_s> seconds before letting it through.
# Usage (from a test's settings.json): hold.sh <log> <hold_s> <scope>
#   scope: main = hold only the main agent's calls · sub = only subagents' calls (input has agent_id) · all
# Writes one line per event to <log>: <ts> <event> …; a hold cut by a signal logs KILLED; a SIGKILL logs nothing (no hold_end).
set -u
log=$1; hold_s=$2; scope=$3
input=$(cat)
agent_id=$(jq -r '.agent_id // ""' <<<"$input")
tool=$(jq -r '.tool_name // ""' <<<"$input")
now() { date -u +%s; }
if { [[ $scope == sub && -z $agent_id ]] || [[ $scope == main && -n $agent_id ]]; }; then
  echo "$(now) pass tool=$tool agent_id=$agent_id" >> "$log"; exit 0
fi
for sig in TERM INT HUP; do
  trap "echo \"\$(date -u +%s) KILLED signal=$sig tool=$tool agent_id=$agent_id\" >> '$log'; exit 1" "$sig"
done
echo "$(now) hold_start hold_s=$hold_s tool=$tool agent_id=$agent_id pid=$$" >> "$log"
sleep "$hold_s" & wait $!
echo "$(now) hold_end tool=$tool agent_id=$agent_id" >> "$log"
exit 0
