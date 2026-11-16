#!/usr/bin/env bash
# PreToolUse hook for the I2 follow-up tests: a copy of hold.sh whose hold also ends early when a release file appears
# (the mechanism the real hook will use for `agent-quota resume-now`).
# Usage (from a test's settings.json): hold_release.sh <log> <hold_s> <scope> <release_dir>
#   scope: main = hold only the main agent's calls · sub = only subagents' calls (input has agent_id) · all
#   release: the hold ends at the first check (every 5 s) that finds <release_dir>/release_main (main agent's calls)
#            or <release_dir>/release_sub (a subagent's calls), or after <hold_s> seconds.
# Writes one line per event to <log>: <ts> <event> …; hold_end says reason=release|timeout; a signal logs KILLED.
set -u
log=$1; hold_s=$2; scope=$3; release_dir=$4
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
kind=main; [[ -n $agent_id ]] && kind=sub
release="$release_dir/release_$kind"
t0=$(now)
echo "$t0 hold_start hold_s=$hold_s tool=$tool agent_id=$agent_id kind=$kind pid=$$" >> "$log"
reason=timeout
while (( $(now) - t0 < hold_s )); do
  if [[ -e $release ]]; then reason=release; break; fi
  sleep 5 & wait $!
done
echo "$(now) hold_end reason=$reason tool=$tool agent_id=$agent_id kind=$kind" >> "$log"
exit 0
