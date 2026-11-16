#!/usr/bin/env bash
# The I2 follow-up tests (2026-11-16): a background subagent, two holds at once, a release file. `claude -p`, Haiku.
# Usage: bash run_more.sh <out_dir>
# Reads   hold_release.sh (beside this file)
# Writes  <out_dir>/<test>/{settings.json, hook.log, marker_main, marker_sub, releases, stream.log, stderr.log, times},
#         <out_dir>/summary.txt
# Runs 3 `claude -p` sessions at once:
#   T1_bg_sub     a background subagent's Bash call held 120 s (scope sub); the main agent keeps making Bash calls
#   T2_two_holds  main and background subagent both held (scope all); sub released 60 s, main 150 s after their hold_start
#   T3_release    the main agent's call held up to 300 s; the test creates release_main 30 s after hold_start
# stream.log: each stream-json line of the session, prefixed with the Unix second it was read.
set -u
out=$1
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$out"

session() {  # session <name> <hold_s> <scope> <prompt>
  local name=$1 hold_s=$2 scope=$3 prompt=$4 d="$out/$1"
  mkdir -p "$d"
  jq -n --arg hold "$here/hold_release.sh" --arg log "$d/hook.log" --arg h "$hold_s" --arg s "$scope" \
        --arg r "$d" --argjson t $((hold_s + 100)) '
    {hooks: {PreToolUse: [{matcher: "Bash", hooks: [
      {type: "command", command: "bash", args: [$hold, $log, $h, $s, $r], timeout: $t, onFailure: "block"}]}]}}' \
    > "$d/settings.json"
  prompt=${prompt//SUBMARKER/$d/marker_sub}; prompt=${prompt//MAINMARKER/$d/marker_main}
  local t0; t0=$(date -u +%s)
  (cd "$d" && claude -p "$prompt" --model haiku --settings "$d/settings.json" --allowedTools Bash Agent \
      --max-turns 15 --output-format stream-json --verbose 2> "$d/stderr.log" \
    | while IFS= read -r line; do printf '%s %s\n' "$(date -u +%s)" "$line"; done > "$d/stream.log")
  echo "start=$t0 end=$(date -u +%s)" > "$d/times"
}

release_after() {  # release_after <name> <kind> <delay_s>: create release_<kind> <delay_s> after that kind's hold_start
  local d="$out/$1" kind=$2 delay=$3 waited=0
  until grep -q "hold_start.*kind=$kind" "$d/hook.log" 2>/dev/null; do
    sleep 1; waited=$((waited + 1)); (( waited > 600 )) && { echo "never held: $kind" >> "$d/releases"; return; }
  done
  sleep "$delay"
  touch "$d/release_$kind"
  echo "$(date -u +%s) created release_$kind" >> "$d/releases"
}

sub_bg='Use the Agent tool exactly once, with run_in_background set to true (subagent_type general-purpose), asking the subagent to run exactly this shell command with its Bash tool, once: `date -u +%s >> SUBMARKER`, then to reply DONE (or BLOCKED if the call is blocked; no retry).'
p1="$sub_bg"' While it runs, do not just wait: with your own Bash tool, run `sleep 20; date -u +%s >> MAINMARKER` three times, one call after the other. Then, once the subagent has reported, reply with what it said and how many lines MAINMARKER has.'
p2="$sub_bg"' Right after launching it, run with your own Bash tool, once: `date -u +%s >> MAINMARKER`. Then, once the subagent has reported, reply with what it said.'
p3='Run exactly this shell command with the Bash tool, once: `date -u +%s >> MAINMARKER`. If the tool call is blocked or fails, do not retry: reply BLOCKED. Otherwise reply DONE.'

session T1_bg_sub    120 sub "$p1" &
session T2_two_holds 300 all "$p2" &
release_after T2_two_holds sub 60 &
release_after T2_two_holds main 150 &
session T3_release   300 main "$p3" &
release_after T3_release main 30 &
wait

{
  for d in "$out"/*/; do
    n=$(basename "$d")
    echo "== $n  $(cat "$d/times" 2>/dev/null)"
    for m in main sub; do echo "   marker_$m: $( { tr '\n' ' ' < "$d/marker_$m"; } 2>/dev/null || echo none)"; done
    sed 's/^/   hook: /' "$d/hook.log" 2>/dev/null
    sed 's/^/   release: /' "$d/releases" 2>/dev/null
    # the session's tool calls and results, one line each, with the second they were seen
    awk '{ts=$1; $1=""; print ts "\t" $0}' "$d/stream.log" | while IFS=$'\t' read -r ts j; do
      jq -r --arg ts "$ts" '
        if .type == "assistant" then (.message.content[]? | select(.type == "tool_use")
              | "   \($ts) call \(.name) \(.input.command // .input.description // "" | .[0:70])"
              + (if .input.run_in_background then " [background]" else "" end)
              + (if $parent != null then " (sub)" else "" end))
        elif .type == "user" then (.message.content[]? | select(.type? == "tool_result")
              | "   \($ts) result \((.content | if type == "array" then (map(.text? // "") | join(" ")) else tostring end) | gsub("\n"; " ") | .[0:90])"
              + (if $parent != null then " (sub)" else "" end))
        elif .type == "result" then "   \($ts) END \(.subtype) is_error=\(.is_error) turns=\(.num_turns) $\(.total_cost_usd) · \(.result // "" | gsub("\n"; " ") | .[0:120])"
        elif .type == "system" and .subtype != "init" then "   \($ts) system \(.subtype)"
        else empty end' --argjson parent "$(jq -c '.parent_tool_use_id' <<<"$j" 2>/dev/null || echo null)" <<<"$j" 2>/dev/null
    done
    if [[ -s $d/stderr.log ]]; then echo "   stderr: $(tail -c 300 "$d/stderr.log")"; fi
  done
} > "$out/summary.txt"
