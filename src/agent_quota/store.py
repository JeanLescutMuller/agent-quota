"""The protector's state on disk (protector/DESIGN.md §1, §5, §6), and the recompute that ties the modules together.

Everything lives under paths.home() ($AGENT_QUOTA_HOME, default ~/opt/agent-quota/state):
    decisions.json          the decisions now: {ts, dt, mode, meters, projections, shared_state, decisions: {sid: …}}
    decisions.jsonl         one line per recompute: readings, projections, harm, cost, candidates and why (R47)
    sessions/<sid>.json     what the hook saw of each session: label, cwd, first/last call, agent ids, interactive
    overrides.json          {sid: {kind: go_on|resume_now, until, at}} (R46)
    mode                    off | observe | on (default observe, R3)
    statusline.txt          one short line for agent-statusline (R45)
    hook-errors.log         every exception the hook swallowed (it fails open, DESIGN §8)
    hook.log                one line per hold and release
    recompute.lock          fcntl lock: one recompute at a time; the others use the existing decisions
Every whole-file write is a temp file + rename.
"""

import contextlib
import fcntl
import json
import os
import re
import time

from . import config as C
from . import paths

MODES = ('off', 'observe', 'on')
DEFAULT_MODE = 'observe'
SESSION_KEEP_S = 24 * 3600     # sessions seen in the last 24 h get a decision (and appear in status)
MAX_AGENT_IDS = 100            # cap on the agent ids kept per session
HISTORY_S = 6 * 3600           # quota history read for the burn rate (forecast.burn_rate: "now − 6 h is plenty")


def _path(*parts):
    return paths.home().joinpath(*parts)


def _dt(ts):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts)) if ts else None


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return default


def write_json(path, obj):
    # temp file + rename: a reader never sees half a file; the pid keeps concurrent writers off each other's temp
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str))
    os.replace(tmp, path)


def append_line(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as f:
        f.write(text.rstrip('\n') + '\n')


def log_event(name, text):
    """A dated line in hook.log / hook-errors.log."""
    now = time.time()
    append_line(_path(name), f'{int(now)} {_dt(now)} pid={os.getpid()} {text}')


# --- mode ---------------------------------------------------------------------------------------------------------
def get_mode():
    try:
        mode = _path('mode').read_text().strip()
    except OSError:
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(mode):
    if mode not in MODES:
        raise ValueError(f'mode must be one of {", ".join(MODES)}')
    p = _path('mode')
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f'.mode.{os.getpid()}.tmp')
    tmp.write_text(mode + '\n')
    os.replace(tmp, p)


# --- sessions registry ----------------------------------------------------------------------------------------------
def _session_path(sid):
    return _path('sessions', re.sub(r'[^A-Za-z0-9_.-]', '_', sid) + '.json')


def is_interactive(env):
    """Claude Code sets CLAUDE_CODE_ENTRYPOINT in its own environment, which its hooks inherit: 'cli' for a session
    Jean types in; 'sdk-cli' for `claude -p`, 'sdk-py'/'sdk-ts' for the Agent SDK (counted over Jean's transcripts,
    2026-11-16). CLAUDE_CODE_SESSION_ATTENDED=0, when set, overrides it to not interactive."""
    if env.get('CLAUDE_CODE_SESSION_ATTENDED') == '0':
        return False
    return env.get('CLAUDE_CODE_ENTRYPOINT') == 'cli'


def record_session(d_input, env, now):
    """Update sessions/<sid>.json from one hook call; returns the session dict (None without a session id)."""
    sid = d_input.get('session_id')
    if not isinstance(sid, str) or not sid:
        return None
    p = _session_path(sid)
    s = read_json(p, {})
    s.setdefault('session_id', sid)
    s.setdefault('first_ts', now)
    s['last_ts'], s['dt'] = now, _dt(now)
    s.setdefault('first_dt', _dt(s['first_ts']))
    s['ts'] = now
    if d_input.get('cwd'):
        s['cwd'] = d_input['cwd']
    if env.get('AGENT_QUOTA_JOB') is not None:
        s['label'] = env['AGENT_QUOTA_JOB'].strip().lower()
    s.setdefault('label', '')
    s['entrypoint'] = env.get('CLAUDE_CODE_ENTRYPOINT', '')
    s['interactive'] = is_interactive(env)
    agent_id = d_input.get('agent_id')
    if agent_id:
        l_ids = s.get('agent_ids') or []
        if agent_id not in l_ids:
            s['agent_ids'] = (l_ids + [agent_id])[-MAX_AGENT_IDS:]
    s['calls'] = int(s.get('calls', 0)) + 1
    write_json(p, s)
    return s


def claim_once(sid, key):
    """True for the first process to claim (sid, key), False for every other: an O_EXCL file, so two hooks of the
    same session (main agent and a subagent) held at the same moment notify Jean once. Older claims are dropped."""
    folder = _path('notified')
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[^A-Za-z0-9_.-]', '_', sid)
    name = f'{stem}@{re.sub(r"[^A-Za-z0-9_.-]", "_", str(key))}'
    try:
        os.close(os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    for p in folder.glob(f'{stem}@*'):
        if p.name != name:
            with contextlib.suppress(OSError):
                p.unlink()
    return True


def load_sessions(since_ts=None):
    d_out = {}
    folder = _path('sessions')
    if not folder.is_dir():
        return d_out
    for p in folder.glob('*.json'):
        s = read_json(p, None)
        if isinstance(s, dict) and s.get('session_id') and (since_ts is None or (s.get('last_ts') or 0) >= since_ts):
            d_out[s['session_id']] = s
    return d_out


def resolve_session(prefix):
    """A session id from its first characters (as Jean types it); raises ValueError when none or several match."""
    l_ids = sorted(set(load_sessions()) | set(load_decisions().get('decisions', {})))
    l_hits = [sid for sid in l_ids if sid == prefix] or [sid for sid in l_ids if sid.startswith(prefix)]
    if len(l_hits) != 1:
        raise ValueError(f'{len(l_hits)} sessions match {prefix!r}' + (f': {", ".join(l_hits[:5])}' if l_hits else ''))
    return l_hits[0]


# --- overrides (R46) ----------------------------------------------------------------------------------------------
def load_overrides(now=None):
    d = read_json(_path('overrides.json'), {})
    if not isinstance(d, dict):
        return {}
    return {sid: o for sid, o in d.items() if now is None or (o.get('until') or 0) > now}


def set_override(sid, kind, until, now):
    d = load_overrides(now)   # expired ones are dropped on every write
    d[sid] = {'kind': kind, 'until': until, 'until_dt': _dt(until), 'at': now, 'dt': _dt(now)}
    write_json(_path('overrides.json'), d)
    return d[sid]


# --- decisions ----------------------------------------------------------------------------------------------------
def load_decisions():
    d = read_json(_path('decisions.json'), {})
    return d if isinstance(d, dict) else {}


def _plain(obj):
    # a dataclass (Meter, Projection, Reading…) or anything with __dict__ → a dict for JSON
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, '__dataclass_fields__'):
        return {k: _plain(getattr(obj, k)) for k in obj.__dataclass_fields__}
    if hasattr(obj, '_asdict'):
        return _plain(obj._asdict())
    return str(obj)


def statusline_text(doc, mode):
    """⏸ 2 paused · resumes 19:00 (DESIGN §6); empty when nothing is paused and the quota is visible."""
    l_frozen = [d for d in doc.get('decisions', {}).values() if d.get('action') == 'freeze']
    if doc.get('error'):
        return 'agent-quota: quota not visible'
    l_stale = [n for n, m in (doc.get('meters') or {}).items() if isinstance(m, dict) and m.get('stale')]
    if not l_frozen:
        return f'agent-quota: {l_stale[0]} reading too old' if l_stale else ''
    resets = min([d.get('cause_resets_at') for d in l_frozen if d.get('cause_resets_at')] or [0])
    when = time.strftime('%H:%M', time.localtime(resets)) if resets else '?'
    if mode == 'on':
        return f'⏸ {len(l_frozen)} paused · resumes {when}'
    return f'agent-quota ({mode}): would pause {len(l_frozen)} · until {when}'


@contextlib.contextmanager
def recompute_lock(wait=False):
    """Non-blocking by default: yields True when this process holds the lock, False when another one does.
    wait=True (a forced recompute, from the command line) waits for it instead."""
    p = _path('recompute.lock')
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a+') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def decision_max_age_s():
    return float(os.environ.get('AGENT_QUOTA_DECISION_MAX_AGE_S') or C.DECISION_MAX_AGE_S)


def gather(now):
    """Read the tracker and run the shared check (DESIGN §3): meters, projections (each with its rate), shared state.
    Imported here so the hook's fast path (mode off) never loads the reading code.
    Raises when the quota history cannot be read: the caller then keeps the decisions as they were (R41)."""
    from . import reading, state

    now = int(now)
    meters = reading.read_meters(now)
    l_hist = reading.meter_history(now - HISTORY_S)
    check = state.shared_check(meters, l_hist, now)
    return meters, {'window': check.window, 'week': check.week}, check


def recompute(now=None, force=False):
    """Recompute decisions.json when older than DECISION_MAX_AGE_S (or when forced). One process at a time:
    if another holds the lock, return the existing decisions. Returns the decisions document."""
    from . import protector

    now = time.time() if now is None else now
    doc = load_decisions()
    if not force and now - (doc.get('ts') or 0) < decision_max_age_s():
        return doc
    with recompute_lock(wait=force) as got:
        if not got:
            return doc
        doc = load_decisions()   # someone may have written it while we waited for the lock
        if not force and now - (doc.get('ts') or 0) < decision_max_age_s():
            return doc
        mode = get_mode()
        sessions = load_sessions(now - SESSION_KEEP_S)
        overrides = load_overrides(now)
        previous = doc.get('decisions') or {}
        error = None
        try:
            meters, projections, shared = gather(now)
            from . import reading
            usd = reading.session_usd(int(now) - C.RECENT_MIN * 60, int(now))
            error = getattr(meters, 'error', None)
        except Exception as e:
            # the tracker cannot be read: decide on unknown meters, which keeps every freeze as it was, freezes
            # nothing new, and still applies Jean's overrides; say so (R41)
            meters, projections, shared, usd = None, {}, None, {}
            error = f'{type(e).__name__}: {e}'
        trace = {}
        d_dec = protector.decide(now, meters, projections, sessions, usd, overrides, C, previous=previous, trace=trace)
        d_meters = {name: _plain(getattr(meters, name, None)) for name in ('window', 'week')}
        d_proj, d_shared = _plain(projections), _plain(shared)
        new = {'ts': now, 'dt': _dt(now), 'mode': mode, 'error': error, 'meters': d_meters,
               'source': getattr(meters, 'source', None), 'machine': getattr(meters, 'machine', None),
               'projections': d_proj, 'shared_state': d_shared,
               'decisions': {sid: d.to_dict() for sid, d in d_dec.items()}}
        write_json(_path('decisions.json'), new)
        # R47: one line per recompute, with everything the decision used and why each candidate was or was not frozen
        append_line(_path('decisions.jsonl'), json.dumps(_plain({
            'ts': now, 'dt': _dt(now), 'mode': mode, 'error': new['error'], 'meters': d_meters, 'projections': d_proj,
            'shared_state': d_shared, 'usd_by_session': usd, 'trace': trace,
            'decisions': {sid: {'action': d.action, 'reason': d.reason, 'cause': d.cause, 'label': d.label,
                                'usd_recent': d.usd_recent, 'window_pct_per_hour': d.window_pct_per_hour}
                          for sid, d in d_dec.items()}}), default=str))
        write_statusline(statusline_text(new, mode))
        return new


def write_statusline(text):
    p = _path('statusline.txt')
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f'.statusline.txt.{os.getpid()}.tmp')
    tmp.write_text(text + ('\n' if text else ''))
    os.replace(tmp, p)
