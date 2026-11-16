#!/usr/bin/env bash
# End-to-end test of the real agent-quota hook with `claude -p` (protector/DESIGN.md, Acceptance).
# Usage: bash run_e2e.sh <out_dir>
# Reads   ../../bin/agent-quota (the repo's code, not the deployed copy)
# Writes  <out_dir>/<test>/{home/ (AGENT_QUOTA_HOME), settings.json, marker, result.json, stderr.log, events}, <out_dir>/summary.txt
# Each test: the session's 1st Bash call registers it and lasts 15 s; meanwhile a freeze is forced into its decisions.json;
# its 2nd Bash call (main agent, or a subagent in E3) is then held, until `agent-quota resume-now` 40 s later.
#   E1_on        mode on       → 2nd call held ≈ 40 s, released by resume-now
#   E2_observe   mode observe  → 2nd call never held
#   E3_sub       mode on, the 2nd call made by a subagent → held too, released by resume-now
set -u
out=$1
repo=$(cd "$(dirname "$0")/../.." && pwd)
aq="$repo/bin/agent-quota"
mkdir -p "$out"

one() {  # one <name> <mode> <prompt>
  local name=$1 mode=$2 prompt=$3 d="$out/$1"
  mkdir -p "$d/home"; echo "$mode" > "$d/home/mode"
  jq -n --arg aq "$aq" '{hooks: {PreToolUse: [{matcher: "*", hooks: [
      {type: "command", command: "python3", args: ["-I", $aq, "hook"], timeout: 600}]}]}}' > "$d/settings.json"
  export AGENT_QUOTA_HOME="$d/home" AGENT_QUOTA_DECISION_MAX_AGE_S=100000 AGENT_QUOTA_NOTIFY=/usr/bin/true \
         AGENT_QUOTA_NO_CAFFEINATE=1 AGENT_QUOTA_OVERRIDE_POLL_S=2
  (cd "$d" && claude -p "${prompt//MARKER/$d/marker}" --model haiku --settings "$d/settings.json" \
      --allowedTools Bash Agent --max-turns 10 --output-format json > "$d/result.json" 2> "$d/stderr.log") &
  local pid=$! sid=""
  for _ in $(seq 60); do  # wait for the hook to register the session
    sid=$(ls "$d/home/sessions" 2>/dev/null | head -1 | sed 's/\.json$//'); [[ -n $sid ]] && break; sleep 1
  done
  echo "$(date -u +%s) registered $sid" >> "$d/events"
  python3 - "$d/home/decisions.json" "$sid" <<'PY'
import json, sys, time
p, sid = sys.argv[1], sys.argv[2]
try: doc = json.load(open(p))
except Exception: doc = {}
now = time.time()
doc.update(ts=now, decisions={sid: {'action': 'freeze', 'reason': 'e2e test: forced freeze', 'frozen_since': now}})
json.dump(doc, open(p + '.tmp', 'w')); __import__('os').replace(p + '.tmp', p)
PY
  echo "$(date -u +%s) freeze forced" >> "$d/events"
  sleep 55
  python3 -I "$aq" resume-now "$sid" > /dev/null 2>&1
  echo "$(date -u +%s) resume-now" >> "$d/events"
  wait $pid
  echo "$(date -u +%s) claude exit $?" >> "$d/events"
}

two='Run these two shell commands with the Bash tool, one after the other, each exactly once: first `date -u +%s >> MARKER; sleep 15`, then `date -u +%s >> MARKER`. If a call is blocked, do not retry. Reply DONE.'
sub='First run with your Bash tool, exactly once: `date -u +%s >> MARKER; sleep 15`. Then use the Agent tool once (subagent_type general-purpose, foreground) and ask the subagent to run with its Bash tool, exactly once: `date -u +%s >> MARKER`, and to reply DONE. Then reply with what it said.'

one E1_on      on      "$two" &
one E2_observe observe "$two" &
one E3_sub     on      "$sub" &
wait

{
  for d in "$out"/*/; do
    echo "== $(basename "$d")"
    echo "   marker: $(tr '\n' ' ' < "$d/marker" 2>/dev/null || echo none)"
    sed 's/^/   event: /' "$d/events"
    sed 's/^/   hook: /' "$d/home/hook.log" 2>/dev/null
    echo "   result: $(jq -r '[.subtype, (.result // "" | .[0:100])] | join(" · ")' "$d/result.json" 2>/dev/null)"
    [[ -s $d/home/hook-errors.log ]] && echo "   hook-errors: $(tail -c 300 "$d/home/hook-errors.log")"
  done
} > "$out/summary.txt"
