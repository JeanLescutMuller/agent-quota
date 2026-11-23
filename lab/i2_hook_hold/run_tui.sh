#!/usr/bin/env bash
# The I2 interactive test (2026-11-16): a real `claude` TUI in tmux, its Bash call held 120 s by hold_release.sh.
# Usage: bash /Users/jeanlescut/dev/agents/agent-tracker/tests/run_with_test_tmux.sh bash run_tui.sh <out_dir>
#   Refuses to run outside run_with_test_tmux.sh: every tmux call names the guard's throwaway socket (-S), never Jean's server.
# Reads   hold_release.sh (beside this file)
# Writes  <out_dir>/<test>/{settings.json, launch.sh, hook.log, marker_main, events, screens/<ts>_<label>.txt},
#         <out_dir>/summary.txt
# Three TUI sessions at once, Haiku, one prompt each that makes one Bash call (scope main, hold 120 s):
#   U1_type    during the hold, text is typed in the input box (no Enter)   → is the TUI responsive? is the hold kept?
#   U2_submit  during the hold, a message is typed and sent with Enter      → does it cancel the hold (#104363)?
#   U3_escape  during the hold, Esc is pressed                              → does Esc cancel the hold and the call?
set -u
[[ -n ${TEST_TMUX_SOCKET:-} ]] || { echo "run under run_with_test_tmux.sh" >&2; exit 2; }
out=$1
here=$(cd "$(dirname "$0")" && pwd)
sock=$TEST_TMUX_SOCKET
t() { tmux -S "$sock" "$@"; }
mkdir -p "$out"
hold_s=120
prompt='Run exactly this shell command with the Bash tool, once: `date -u +%s >> MAINMARKER`. If the tool call is blocked or fails, do not retry: reply BLOCKED. Otherwise reply DONE.'

shot() {  # shot <name> <label>: save the pane's screen
  local d="$out/$1"
  t capture-pane -p -t "$1" > "$d/screens/$(date -u +%s)_$2.txt" 2>/dev/null
}
ev() { echo "$(date -u +%s) $2" >> "$out/$1/events"; }

one() {  # one <name> <action during the hold: type|submit|escape>
  local name=$1 action=$2 d="$out/$1" i
  mkdir -p "$d/screens"
  jq -n --arg hold "$here/hold_release.sh" --arg log "$d/hook.log" --arg h "$hold_s" --arg r "$d" \
        --argjson t $((hold_s + 100)) '
    {hooks: {PreToolUse: [{matcher: "Bash", hooks: [
      {type: "command", command: "bash", args: [$hold, $log, $h, "main", $r], timeout: $t, onFailure: "block"}]}]}}' \
    > "$d/settings.json"
  # the prompt is typed once the TUI is ready: a prompt given as an argument is dropped by the folder-trust dialog
  printf '#!/usr/bin/env bash\ncd %q && exec claude --model haiku --settings %q --allowedTools Bash\n' \
    "$d" "$d/settings.json" > "$d/launch.sh"
  t new-session -d -s "$name" -x 160 -y 45 "bash $d/launch.sh; sleep 600"
  ev "$name" "started"
  # first screens: accept the folder-trust dialog if it shows, then type the prompt once the input box is there
  local sent=""
  for i in $(seq 1 60); do
    grep -q hold_start "$d/hook.log" 2>/dev/null && break
    if [[ -z $sent ]] && t capture-pane -p -t "$name" | grep -q 'Claude Code v' \
       && ! t capture-pane -p -t "$name" | grep -q 'trust this folder'; then
      sleep 2; t send-keys -t "$name" -l "${prompt//MAINMARKER/$d/marker_main}"; sleep 1; t send-keys -t "$name" Enter
      sent=1; ev "$name" "prompt typed + Enter"; shot "$name" prompt_sent
    fi
    if t capture-pane -p -t "$name" | grep -q 'Yes, I trust this folder'; then  # the default choice is "No, exit"
      shot "$name" trust_dialog; t send-keys -t "$name" Down; sleep 1; t send-keys -t "$name" Enter
      ev "$name" "trust dialog: Down + Enter"; sleep 3
    fi
    sleep 2
  done
  grep -q hold_start "$d/hook.log" 2>/dev/null || { ev "$name" "never held"; shot "$name" never_held; return; }
  ev "$name" "hold_start seen"
  sleep 5; shot "$name" hold_5s
  sleep 20
  case $action in
    type)   t send-keys -t "$name" -l 'typed while frozen'; ev "$name" "typed text (no Enter)" ;;
    submit) t send-keys -t "$name" -l 'What is 2+2? Answer in one word.'; sleep 1; t send-keys -t "$name" Enter
            ev "$name" "typed a message + Enter" ;;
    escape) t send-keys -t "$name" Escape; ev "$name" "pressed Escape" ;;
  esac
  sleep 3; shot "$name" after_action
  for i in $(seq 1 30); do  # every 10 s until the hold has ended, then 30 s more
    sleep 10; shot "$name" poll
    grep -q 'hold_end\|KILLED' "$d/hook.log" 2>/dev/null && break
  done
  ev "$name" "hold over: $(tail -1 "$d/hook.log")"
  sleep 30; shot "$name" final
  ev "$name" "marker: $(tr '\n' ' ' < "$d/marker_main" 2>/dev/null || echo none)"
  t send-keys -t "$name" C-c; sleep 1; t send-keys -t "$name" C-c; sleep 2
  t kill-session -t "$name" 2>/dev/null
  ev "$name" "session killed"
}

one U1_type type &
one U2_submit submit &
one U3_escape escape &
wait
t kill-server 2>/dev/null

{
  for d in "$out"/*/; do
    n=$(basename "$d")
    echo "== $n"
    sed 's/^/   event: /' "$d/events" 2>/dev/null
    sed 's/^/   hook: /' "$d/hook.log" 2>/dev/null
    echo "   marker_main: $(tr '\n' ' ' < "$d/marker_main" 2>/dev/null || echo none)"
  done
} > "$out/summary.txt"
