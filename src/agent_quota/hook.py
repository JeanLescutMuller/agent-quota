"""The PreToolUse hook (protector/DESIGN.md §1, §6–8): `agent-quota hook`, on every tool call of every session.

    stdin: Claude Code's hook JSON (session_id, agent_id when in a subagent, tool_name, cwd, …)
    mode off       → exit 0 at once (nothing read, nothing written)
    otherwise      → record the session; recompute decisions.json when older than DECISION_MAX_AGE_S
    freeze + on    → (scope `subagents`: only a subagent's call, one with a non-empty `agent_id`, is held; the main
                     thread's calls always pass, R32) notify Jean once (agent-notify), keep the Mac awake (caffeinate -w <own pid>), then hold:
                     every 5 s check overrides.json and the mode; every HOLD_POLL_S re-read decisions (recomputing
                     them when old: a held hook may be the only one left running) until allow
    always         → exit 0, the call runs. Never raises: an exception goes to hook-errors.log (fails open, §8).
                     SIGTERM/SIGINT/SIGHUP (Claude Code's timeout, Jean's Ctrl-C) → exit 0 too.
Env, for tests: AGENT_QUOTA_HOLD_POLL_S, AGENT_QUOTA_OVERRIDE_POLL_S, AGENT_QUOTA_DECISION_MAX_AGE_S,
AGENT_QUOTA_NO_CAFFEINATE=1, AGENT_QUOTA_NOTIFY ('' = never notify;
default: `notify` on PATH).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback

from . import config as C
from . import store

HOLD_MARGIN_S = 60   # stop holding this long before Claude Code's hook timeout would kill us
OVERRIDE_POLL_S = 5  # a held hook checks overrides.json and the mode this often (go-on / resume-now within 5 s)
CAFFEINATE = '/usr/bin/caffeinate'
_HOLD = {}           # the call being held, for the signal handler's log line


def _notify(event, sid):
    """`notify event <event>` for this session's own pane (agent-notify); skipped silently when absent."""
    cmd = os.environ.get('AGENT_QUOTA_NOTIFY')
    cmd = shutil.which('notify') if cmd is None else cmd
    if not cmd:
        return
    try:
        subprocess.run([cmd, 'event', event], env=dict(os.environ, NOTIFY_AGENT_SESSION_ID=sid),
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def _decision(doc, sid):
    d = (doc.get('decisions') or {}).get(sid)
    return d if isinstance(d, dict) else None


def _holds(dec, agent_id):
    """Whether decision `dec` holds a call made by `agent_id` ('' = the main thread): a freeze of scope `subagents`
    holds only subagents' calls; any other freeze holds every call."""
    if not dec or dec.get('action') != 'freeze':
        return False
    return bool(agent_id) or dec.get('scope', 'all') != 'subagents'


def run(raw, env):
    try:
        d_input = json.loads(raw)
    except ValueError:
        store.log_event('hook-errors.log', f'input is not JSON: {raw[:200]!r}')
        return
    if not isinstance(d_input, dict) or not isinstance(d_input.get('session_id'), str):
        store.log_event('hook-errors.log', f'input has no session_id: {raw[:200]!r}')
        return
    mode = store.get_mode()
    if mode == 'off':
        return
    now = time.time()
    sid = d_input['session_id']
    store.record_session(d_input, env, now)
    doc = store.recompute(now)
    dec = _decision(doc, sid)
    agent_id = d_input.get('agent_id') or ''
    if mode != 'on' or not _holds(dec, agent_id) or sid in store.load_overrides(now):
        return

    # --- the freeze: hold this tool call until the decision says allow ------------------------------------------
    poll = float(env.get('AGENT_QUOTA_HOLD_POLL_S') or C.HOLD_POLL_S)                 # re-read decisions.json
    tick = min(poll, float(env.get('AGENT_QUOTA_OVERRIDE_POLL_S') or OVERRIDE_POLL_S))  # re-read overrides, mode
    deadline = now + C.HOOK_TIMEOUT_S - HOLD_MARGIN_S
    tool = d_input.get('tool_name', '')
    _HOLD.update(session=sid, agent_id=agent_id, tool=tool)
    _keep_awake()
    if store.claim_once(sid, dec.get('frozen_since')):   # once per freeze, not per held call
        _notify('WaitingForUser', sid)
    store.log_event('hook.log', f'hold_start session={sid} agent_id={agent_id} tool={tool} reason={dec.get("reason")!r}')
    why, next_read = 'deadline', time.time() + poll
    while time.time() < deadline:
        time.sleep(tick)
        mode = store.get_mode()
        if mode != 'on':
            why = f'mode {mode}'
            break
        if sid in store.load_overrides(time.time()):   # go-on / resume-now: released within one tick
            why = 'override'
            break
        if time.time() >= next_read:
            next_read = time.time() + poll
            dec = _decision(store.recompute(time.time()), sid)
            if not _holds(dec, agent_id):
                why = (dec or {}).get('reason') or 'no decision'
                break
    _HOLD.clear()
    store.log_event('hook.log', f'hold_end session={sid} agent_id={agent_id} tool={tool} why={why!r}')
    _notify('Working', sid)


def _keep_awake():
    """Keep the Mac awake while this hook holds (DESIGN open point 7): caffeinate ends with this process."""
    if os.path.exists(CAFFEINATE) and os.environ.get('AGENT_QUOTA_NO_CAFFEINATE') != '1':
        try:
            subprocess.Popen([CAFFEINATE, '-i', '-w', str(os.getpid())], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            pass


def main(stdin=None, env=None):
    def on_signal(signum, frame):
        # Esc in an interactive session (or Claude Code's timeout) sends SIGTERM: exit 0 quietly. While holding, Esc
        # cancels the held call; the next tool call is simply frozen again (DESIGN open point 6). Writes are atomic.
        if _HOLD:
            try:
                why = 'cancelled by Jean (Esc)' if signum == signal.SIGTERM else f'signal {signum}'
                line = f'hold_end session={_HOLD.get("session")} agent_id={_HOLD.get("agent_id")} tool={_HOLD.get("tool")} why={why!r}'
                store.log_event('hook.log', line)
                store.append_line(store._path('decisions.jsonl'), json.dumps(
                    {'ts': time.time(), 'dt': store._dt(time.time()), 'event': 'hold_cancelled', 'why': why, **_HOLD}))
            except Exception:
                pass
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, on_signal)
    try:
        run((stdin or sys.stdin).read(), os.environ if env is None else env)
    except Exception:
        try:
            store.log_event('hook-errors.log', traceback.format_exc().replace('\n', ' | '))
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
