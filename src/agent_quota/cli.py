"""`agent-quota`: the protector's commands (protector/DESIGN.md §1, §5, §6).

    agent-quota status [--all] [--json]   meters, who acts, sessions with label / $ / decision and the reasons
    agent-quota state --json              the shared check (R1), for the maximizer
    agent-quota decide                    recompute now, print the decisions
    agent-quota go-on <session>           never freeze it until its window resets (R46)
    agent-quota resume-now <session>      release it now, not frozen again until its window resets (R46)
    agent-quota mode [off|observe|on]     print or set the mode (default observe: decide and log, never hold)
    agent-quota hook                      the PreToolUse hook (stdin: Claude Code's hook JSON)
Reads and writes $AGENT_QUOTA_HOME (default ~/opt/agent-quota/state); reads the tracker ($AGENT_QUOTA_TRACKER).
"""

import argparse
import json
import sys
import time

from . import store

WINDOW_FALLBACK_S = 5 * 3600   # go-on / resume-now with no window reset known: one window from now
STATUS_RECENT_S = 3600         # status shows sessions seen in the last hour, and every frozen one (--all: 24 h)


def _hhmm(ts, now=None):
    if not ts:
        return '—'
    fmt = '%H:%M' if abs(ts - (now or time.time())) < 20 * 3600 else '%a %H:%M'
    return time.strftime(fmt, time.localtime(ts))


def _table(l_head, l_rows):
    l_w = [max(len(str(r[i])) for r in [l_head] + l_rows) for i in range(len(l_head))]
    return '\n'.join('  '.join(str(c).ljust(w) for c, w in zip(r, l_w)).rstrip() for r in [l_head] + l_rows)


def _num(x, fmt='{:.0f}'):
    return '—' if x is None else fmt.format(x)


def print_status(doc, all_sessions=False):
    now = time.time()
    mode = store.get_mode()
    print(f'agent-quota · mode {mode} · decided {_hhmm(doc.get("ts"), now)} '
          f'({int(now - (doc.get("ts") or now))} s ago) · reading from {doc.get("source") or "?"}'
          + (f' · ERROR {doc["error"]}' if doc.get('error') else ''))
    shared = doc.get('shared_state') or {}
    d_meters, d_proj = doc.get('meters') or {}, doc.get('projections') or {}
    l_rows = []
    for name in ('window', 'week'):
        m, p = d_meters.get(name) or {}, d_proj.get(name) or {}
        l_rows.append([name, _num(m.get('pct')), _hhmm(m.get('resets_at'), now), _num(p.get('rate'), '{:.3f}'),
                       _hhmm(p.get('full_at'), now), _num(p.get('lockout_min')) + (' min' if p.get('lockout_min') else ''),
                       'stale' if m.get('stale') else 'fresh', shared.get(f'{name}_state', '—')])
    print(_table(['meter', 'quota %', 'reset', 'burn %/min', '100 % at', 'lockout', 'reading', 'state'], l_rows))
    print(f'who acts: {shared.get("who", "—")}'
          + (f' · week spare quota {shared["week_spare_pct"]:.1f} %' if shared.get('week_spare_pct') is not None else ''))
    sessions = store.load_sessions()
    since = now - (store.SESSION_KEEP_S if all_sessions else STATUS_RECENT_S)
    l_rows = []
    for sid, d in sorted((doc.get('decisions') or {}).items(),
                         key=lambda kv: (kv[1].get('action') != 'freeze', -((sessions.get(kv[0]) or {}).get('last_ts') or 0))):
        s = sessions.get(sid) or {}
        if d.get('action') != 'freeze' and (s.get('last_ts') or 0) < since:
            continue
        l_rows.append([sid[:8], d.get('label') or '—', 'yes' if d.get('interactive') else 'no',
                       f'{d.get("usd_recent") or 0:.2f}', _num(d.get('window_pct_per_hour'), '{:.1f}'),
                       _hhmm(s.get('last_ts'), now), d.get('action'), (s.get('cwd') or '')[-30:], d.get('reason', '')])
    if l_rows:
        print(_table(['session', 'label', 'inter.', '$ 30 min', '% win/h', 'last call', 'decision', 'folder', 'why'], l_rows))
    else:
        print('no session in the last hour' if not all_sessions else 'no session')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='agent-quota', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('status', help='meters, who acts, sessions and decisions')
    p.add_argument('--json', action='store_true')
    p.add_argument('--all', action='store_true', help='every session of the last 24 h')
    p = sub.add_parser('state', help='the shared check (R1), for the maximizer')
    p.add_argument('--json', action='store_true')
    sub.add_parser('decide', help='recompute the decisions now and print them')
    for name, help_ in (('go-on', 'never freeze this session until its window resets'),
                        ('resume-now', 'release this session now')):
        sub.add_parser(name, help=help_).add_argument('session', help='session id, or its first characters')
    p = sub.add_parser('mode', help='print or set the mode')
    p.add_argument('mode', nargs='?', choices=store.MODES)
    sub.add_parser('hook', help='the PreToolUse hook (stdin: hook JSON)')
    a = ap.parse_args(argv)

    if a.cmd == 'hook':
        from . import hook
        return hook.main()
    if a.cmd == 'mode':
        if a.mode:
            store.set_mode(a.mode)
        print(store.get_mode())
        return 0
    if a.cmd == 'status':
        doc = store.recompute()
        if a.json:
            print(json.dumps({'decisions_doc': doc, 'sessions': store.load_sessions(time.time() - store.SESSION_KEEP_S),
                              'overrides': store.load_overrides(time.time()), 'mode': store.get_mode(),
                              'statusline': store.statusline_text(doc, store.get_mode())}, indent=1, default=str))
        else:
            print_status(doc, a.all)
        return 0
    if a.cmd == 'state':
        doc = store.recompute()
        shared = doc.get('shared_state') or {}
        out = {'ts': doc.get('ts'), 'dt': doc.get('dt'), 'who': shared.get('who', 'nobody'),
               'window_state': shared.get('window_state'), 'week_state': shared.get('week_state'),
               'week_spare_pct': shared.get('week_spare_pct'), 'error': doc.get('error'), 'mode': store.get_mode(),
               'frozen': sorted(sid for sid, d in (doc.get('decisions') or {}).items() if d.get('action') == 'freeze'),
               'shared_state': shared}
        print(json.dumps(out, indent=1, default=str) if a.json else out['who'])
        return 0
    if a.cmd == 'decide':
        doc = store.recompute(force=True)
        print_status(doc, all_sessions=True)
        return 0
    if a.cmd in ('go-on', 'resume-now'):
        try:
            sid = store.resolve_session(a.session)
        except ValueError as e:
            print(f'agent-quota: {e}', file=sys.stderr)
            return 2
        now = time.time()
        resets = ((store.load_decisions().get('meters') or {}).get('window') or {}).get('resets_at')
        until = resets if resets and resets > now else now + WINDOW_FALLBACK_S
        store.set_override(sid, a.cmd.replace('-', '_'), until, now)
        doc = store.recompute(now, force=True)   # takes effect now: a held hook sees it at its next poll
        d = (doc.get('decisions') or {}).get(sid) or {}
        print(f'{sid}: {a.cmd} until {_hhmm(until, now)} · decision {d.get("action", "—")}: {d.get("reason", "")}')
        return 0
    return 1


if __name__ == '__main__':
    sys.exit(main())
