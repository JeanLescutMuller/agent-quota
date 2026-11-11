#!/usr/bin/env bash
# The I2 test (protector/CONSIDERATIONS.md §9): can a PreToolUse command hook hold a Claude Code session, and a subagent, for hours?
# Usage: bash run.sh <out_dir> [hold_s]      (hold_s: the long holds, default 18300 = 5 h 05 min)
# Reads   hold.sh (beside this file)
# Writes  <out_dir>/<test>/{settings.json, hook.log, marker, result.json, stderr.log, times}, <out_dir>/summary.txt
# Runs 4 `claude -p` sessions at once (Haiku, a few requests each):
#   A_main     the main agent's Bash call held hold_s (timeout hold_s + 700, onFailure block)
#   B_sub      a subagent's Bash call held hold_s (same)
#   C_block    held 60 s with timeout 15 and onFailure block   → expected: the call is blocked (no marker)
#   C_open     held 60 s with timeout 15, no onFailure          → expected: the call runs anyway (docs: fails open)
set -u
out=$1; long=${2:-18300}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out"

one() {  # one <name> <hold_s> <timeout_s> <scope> <on_failure|""> <prompt>
  local name=$1 hold_s=$2 timeout_s=$3 scope=$4 on_failure=$5 prompt=$6 d="$out/$1"
  mkdir -p "$d"
  jq -n --arg hold "$here/hold.sh" --arg log "$d/hook.log" --arg h "$hold_s" --arg s "$scope" \
        --argjson t "$timeout_s" --arg f "$on_failure" '
    {hooks: {PreToolUse: [{matcher: "Bash", hooks: [
      ({type: "command", command: "bash", args: [$hold, $log, $h, $s], timeout: $t}
       + (if $f == "" then {} else {onFailure: $f} end))]}]}}' > "$d/settings.json"
  local t0; t0=$(date -u +%s)
  (cd "$d" && claude -p "${prompt//MARKER/$d/marker}" --model haiku --settings "$d/settings.json" \
      --allowedTools Bash Agent --max-turns 8 --output-format json > "$d/result.json" 2> "$d/stderr.log")
  local rc=$?
  echo "start=$t0 end=$(date -u +%s) exit=$rc" > "$d/times"
}

cmd='Run exactly this shell command with the Bash tool, once: `date -u +%s >> MARKER`. If the tool call is blocked or fails, do not retry: reply BLOCKED. Otherwise reply DONE.'
sub='Do not use the Bash tool yourself. Use the Agent tool once (subagent_type general-purpose, in the foreground) and ask the subagent to run exactly this shell command with its Bash tool, once: `date -u +%s >> MARKER`, and to reply DONE, or BLOCKED if the call is blocked (no retry). Then reply with what the subagent said.'

one A_main  "$long" $((long + 700)) main  block "$cmd" &
one B_sub   "$long" $((long + 700)) sub   block "$sub" &
one C_block 60      15              all   block "$cmd" &
one C_open  60      15              all   ""    "$cmd" &
wait

{
  for d in "$out"/*/; do
    n=$(basename "$d")
    echo "== $n  $(cat "$d/times" 2>/dev/null)"
    echo "   marker: $(tr '\n' ' ' < "$d/marker" 2>/dev/null || echo none)"
    sed 's/^/   hook: /' "$d/hook.log" 2>/dev/null
    echo "   result: $(jq -r '[.subtype, (.is_error|tostring), (.result // "" | .[0:120])] | join(" · ")' "$d/result.json" 2>/dev/null)"
    [[ -s $d/stderr.log ]] && echo "   stderr: $(tail -c 300 "$d/stderr.log")"
  done
} > "$out/summary.txt"
