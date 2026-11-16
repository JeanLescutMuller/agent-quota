"""The protector's decision (protector/DESIGN.md §4): for each session, allow or freeze, with the reason.

Pure: no file access, no clock. Everything comes in as plain values, so it is tested with plain values.

Inputs (all plain; objects or dicts are both accepted where a field is read):
    now             Unix seconds
    meters          has .window and .week (or a dict with those keys): each a Meter (pct, resets_at, reading_ts,
                    optional stale) or None when the meter is not open
    projections     {'window': {full_at, lockout_min, rate}, 'week': {...}}; rate = burn rate in % of that meter per
                    minute (forecast.burn_rate); full_at = None when 100 % is not reached before the reset
    sessions        {session_id: {label, interactive, last_ts, first_ts, cwd, ...}} (store's sessions registry)
    usd_by_session  {session_id: $ over the last RECENT_MIN minutes} (this machine only)
    overrides       {session_id: {kind: 'go_on'|'resume_now', until: ts, at: ts}}
    config          the config module or a dict; missing names fall back to DEFAULTS (DESIGN §2)
    previous        {session_id: Decision or dict}: the last decisions (who is frozen since when, last release)
    trace           a dict to fill with the meter-level reasoning, for decisions.jsonl (R47)
"""

import time
from dataclasses import asdict, dataclass, field, fields

# DESIGN §2: the values this module owns or reads; config overrides each of them
DEFAULTS = {
    'RESERVE_WINDOW_PCT': 5, 'RESERVE_WEEK_PCT': 5, 'LOCKOUT_VS_DELAY': 10,
    'READING_MAX_AGE_S': 600, 'ACTIVE_MIN': 30, 'P_NEED_ACTIVE': 0.52, 'P_NEED_IDLE': 0.13,
    'BIG_JOB_PCT_PER_HOUR': 10, 'RESUME_STAGGER_MIN': 5,
    'SEEN_MIN': 10,          # "candidates = sessions seen in the last 10 min" (DESIGN §4)
    'REACT_MIN': 5,          # "pct + rate × 5 min ≥ 100 − reserve" (DESIGN §4)
}
METERS = ('week', 'window')  # the week first: the bigger stake (R31); a session frozen by both keeps the week as cause


@dataclass
class Decision:
    session_id: str
    action: str                       # allow | freeze
    reason: str                       # one human sentence
    cause: str | None = None          # the meter that caused the freeze: window | week
    label: str = ''                   # AGENT_QUOTA_JOB: big, big:<pct>, urgent, maximizer, or ''
    interactive: bool = False
    usd_recent: float = 0.0           # $ over the last 30 min
    share: float = 0.0                # its $ ÷ all sessions' $ on this machine, same 30 min
    window_pct_per_hour: float = 0.0  # share × window burn rate × 60: what "big" is judged on
    frozen_since: float | None = None
    cause_resets_at: float | None = None
    rate_at_freeze: float = 0.0       # % of the cause meter per minute it burned when frozen (used to judge release)
    released_at: float | None = None
    numbers: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def _get(obj, name, default=None):
    # read a field from an object or a dict alike
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _hhmm(ts):
    return time.strftime('%H:%M', time.localtime(ts)) if ts else '?'


def _dur(minutes):
    minutes = int(round(minutes))
    return f'{minutes // 60} h {minutes % 60:02d}' if minutes >= 60 else f'{minutes} min'


def parse_label(label):
    """'big:3' → ('big', 3.0); 'big' → ('big', None); anything else → (label, None)."""
    label = (label or '').strip().lower()
    if label.startswith('big:'):
        try:
            return 'big', float(label[4:])
        except ValueError:
            return 'big', None
    return label, None


def assess_meter(name, meter, proj, now, cfg, p_need):
    """The numbers of DESIGN §3–§4 for one meter: lockout ahead, harm vs cost, reserve about to be touched."""
    d_out = {'meter': name, 'open': meter is not None}
    if meter is None or _get(meter, 'pct') is None:   # no reading at all: unknown, act on nothing (R41)
        d_out.update(open=False, stale=True, lockout_ahead=False, act=False, why=f'{name}: no quota reading')
        return d_out
    pct, resets_at = float(_get(meter, 'pct', 0) or 0), _get(meter, 'resets_at')
    reading_ts = _get(meter, 'reading_ts')
    stale = _get(meter, 'stale')
    if stale is None:
        stale = reading_ts is None or now - reading_ts > cfg('READING_MAX_AGE_S')
    reserve = cfg('RESERVE_WEEK_PCT' if name == 'week' else 'RESERVE_WINDOW_PCT')
    full_at, lockout_min = _get(proj, 'full_at'), float(_get(proj, 'lockout_min', 0) or 0)
    rate = _get(proj, 'rate')
    if rate is None and full_at is not None and full_at > now:
        rate = (100 - pct) / ((full_at - now) / 60)  # derive it back when the projection does not carry it
    rate = float(rate or 0)
    minutes_left = max(0.0, (resets_at - now) / 60) if resets_at else 0.0
    d_out.update(pct=pct, resets_at=resets_at, reading_ts=reading_ts, stale=bool(stale), reserve=reserve,
                 rate=rate, full_at=full_at, lockout_min=lockout_min, minutes_left=minutes_left,
                 lockout_ahead=full_at is not None)
    if full_at is None:
        d_out.update(act=False, why=f'no lockout ahead ({name} {pct:.0f} %)')
        return d_out
    harm = lockout_min * p_need * cfg('LOCKOUT_VS_DELAY')      # the cost of doing nothing, in minutes of delay
    cost = max(0.0, (full_at - now) / 60)                      # the work a freeze takes: after full_at, stuck anyway
    reserve_touched = pct + rate * cfg('REACT_MIN') >= 100 - reserve
    act = (harm > cost) and reserve_touched and not stale
    if stale:
        why = f'{name} reading is {int((now - (reading_ts or 0)) / 60)} min old: too old to act on (R41)'
    elif not reserve_touched:
        why = (f'lockout ahead on the {name} (100 % at {_hhmm(full_at)}, {_dur(lockout_min)} of lockout) '
               f'but its reserve is not touched within {cfg("REACT_MIN")} min')
    elif harm <= cost:
        why = (f'lockout ahead on the {name} but not worth a pause: harm {harm:.0f} min '
               f'({_dur(lockout_min)} × {p_need} × {cfg("LOCKOUT_VS_DELAY")}) ≤ cost {cost:.0f} min')
    else:
        why = (f'the {name} reaches 100 % at {_hhmm(full_at)}, {_dur(lockout_min)} before its reset: '
               f'harm {harm:.0f} min > cost {cost:.0f} min')
    d_out.update(harm=harm, cost=cost, reserve_touched=reserve_touched, act=act, why=why)
    return d_out


def decide(now, meters, projections, sessions, usd_by_session, overrides, config, previous=None, trace=None):
    def cfg(name):
        v = _get(config, name)
        return DEFAULTS[name] if v is None else v

    previous = {sid: (d if isinstance(d, Decision) else Decision.from_dict(d)) for sid, d in (previous or {}).items()}
    overrides = overrides or {}
    usd_by_session = usd_by_session or {}

    # --- who is there, and what each burns -----------------------------------------------------------------------
    total_usd = sum(max(0.0, float(v or 0)) for v in usd_by_session.values())
    active_since = now - cfg('ACTIVE_MIN') * 60
    jean_active = any(_get(s, 'interactive') and (_get(s, 'last_ts') or 0) >= active_since for s in sessions.values())
    p_need = cfg('P_NEED_ACTIVE') if jean_active else cfg('P_NEED_IDLE')   # R33

    d_assess = {}
    for name in METERS:
        d_assess[name] = assess_meter(name, _get(meters, name), _get(projections, name), now, cfg, p_need)
    window_rate = d_assess['window'].get('rate', 0.0)

    d_dec = {}
    for sid in set(sessions) | {sid for sid, d in previous.items() if d.action == 'freeze'}:
        s, prev = sessions.get(sid) or {}, previous.get(sid)
        usd = max(0.0, float(usd_by_session.get(sid, 0) or 0))
        share = usd / total_usd if total_usd > 0 else 0.0
        d_dec[sid] = Decision(
            session_id=sid, action='allow', reason='', label=_get(s, 'label') or (prev.label if prev else ''),
            interactive=bool(_get(s, 'interactive', prev.interactive if prev else False)),
            usd_recent=round(usd, 4), share=round(share, 4), window_pct_per_hour=round(share * window_rate * 60, 2),
            released_at=prev.released_at if prev else None)

    def override_of(sid):
        o = overrides.get(sid)
        return o if o and (_get(o, 'until') or 0) > now else None

    # --- release first (R43, R44): previously frozen sessions -------------------------------------------------------
    week = d_assess['week']
    week_full = week.get('open') and not week.get('stale') and week['pct'] >= 100 - week['reserve']
    l_eligible, released_now = [], set()
    for sid, prev in previous.items():
        if prev.action != 'freeze':
            continue
        dec = d_dec[sid]
        dec.cause, dec.frozen_since, dec.cause_resets_at = prev.cause, prev.frozen_since, prev.cause_resets_at
        dec.rate_at_freeze = prev.rate_at_freeze
        o = override_of(sid)
        if o:
            dec.action, dec.released_at = 'allow', now
            dec.reason = f'Jean said {"resume now" if _get(o, "kind") == "resume_now" else "go on"}: released, not paused again until {_hhmm(_get(o, "until"))}'
            released_now.add(sid)
            continue
        a = d_assess.get(prev.cause) or {}
        reset_passed = prev.cause_resets_at is not None and now >= prev.cause_resets_at
        if reset_passed:
            why = f'the {prev.cause} has reset'
        elif a.get('stale') or not a.get('open'):
            why = None
            dec.action, dec.reason = 'freeze', f'still paused: the {prev.cause} reading is too old to judge a release (R41)'
        else:
            # no lockout ahead any more, even with this session's own burn added back: release is safe
            back = a['rate'] + prev.rate_at_freeze
            safe = not a['lockout_ahead'] and a['pct'] + back * a['minutes_left'] < 100 - a['reserve']
            why = f'no lockout ahead on the {prev.cause} any more, even with its own burn back' if safe else None
            if not safe:
                dec.action = 'freeze'
                dec.reason = f'still paused: the {prev.cause} would reach 100 % before its reset at {_hhmm(a.get("resets_at"))}'
        if why is None:
            continue
        if week_full:
            dec.action = 'freeze'
            dec.reason = f'{why}, but the week is at {week["pct"]:.0f} %: waiting for the week (R44)'
            continue
        dec.action, dec.reason = 'freeze', f'{why}: waiting its turn (one resume every {cfg("RESUME_STAGGER_MIN")} min)'
        l_eligible.append(dec)

    # stagger: at most one release every RESUME_STAGGER_MIN, urgent first, then the oldest freeze (R44)
    last_release = max([d.released_at for d in previous.values() if d.released_at] or [0])
    if l_eligible and now - last_release >= cfg('RESUME_STAGGER_MIN') * 60:
        l_eligible.sort(key=lambda d: (parse_label(d.label)[0] != 'urgent', d.frozen_since or 0))
        first = l_eligible[0]
        first.action, first.released_at = 'allow', now
        first.reason = first.reason.split(': waiting its turn')[0] + ': resumed'
        released_now.add(first.session_id)

    # --- candidates (DESIGN §4) ------------------------------------------------------------------------------------
    seen_since = now - cfg('SEEN_MIN') * 60
    d_candidates, d_not = {}, {}   # sid → Decision; sid → why not a candidate
    for sid, dec in d_dec.items():
        if dec.action == 'freeze' or sid in released_now or (previous.get(sid) and previous[sid].action == 'freeze'):
            continue
        s = sessions.get(sid) or {}
        kind, _ = parse_label(dec.label)
        o = override_of(sid)
        if (_get(s, 'last_ts') or 0) < seen_since:
            d_not[sid] = f'no tool call in the last {cfg("SEEN_MIN")} min'
        elif kind == 'urgent':
            d_not[sid] = 'labelled urgent: never paused (R40)'
        elif o:
            d_not[sid] = f'Jean said go on: not paused until {_hhmm(_get(o, "until"))} (R46)'
        elif dec.interactive and kind != 'big':
            d_not[sid] = 'interactive session: never paused in v1 (R32)'
            if dec.window_pct_per_hour >= cfg('BIG_JOB_PCT_PER_HOUR'):
                d_not[sid] += f'; warning: it burns {dec.window_pct_per_hour:.0f} % of a window per hour'
        elif kind not in ('big', 'maximizer') and dec.window_pct_per_hour < cfg('BIG_JOB_PCT_PER_HOUR'):
            d_not[sid] = (f'small work: {dec.window_pct_per_hour:.1f} % of a window per hour, '
                          f'under {cfg("BIG_JOB_PCT_PER_HOUR")}')
        else:
            d_candidates[sid] = dec

    # --- freezes, meter by meter (R37, R39) -------------------------------------------------------------------------
    d_why = {sid: [] for sid in d_candidates}   # per candidate: why it was or was not frozen, per meter
    d_trace_meters = {}
    for name in METERS:
        a = d_assess[name]
        d_trace_meters[name] = dict(a, frozen=[])
        if not a['lockout_ahead'] or not a['act']:
            for sid in d_candidates:
                if d_candidates[sid].action != 'freeze':
                    d_why[sid].append(a['why'])
            continue
        target, minutes_left = 100 - a['reserve'], a['minutes_left']
        # the remaining rate, minus what the sessions frozen so far (this round or before) were burning
        remaining = a['rate'] - sum(a['rate'] * d.share for d in d_dec.values() if d.action == 'freeze')

        def reaches(r):
            return a['pct'] + r * minutes_left >= target

        def order(d):
            kind, _ = parse_label(d.label)
            return ({'maximizer': 0, 'big': 1}.get(kind, 2), -d.usd_recent)

        for dec in sorted((d for d in d_candidates.values() if d.action != 'freeze'), key=order):
            kind, need = parse_label(dec.label)
            if need is not None and need <= 100 - a['pct']:
                d_why[dec.session_id].append(f'labelled big:{need:g}: it fits in the {100 - a["pct"]:.0f} % left of the {name} (R36)')
                continue
            if not reaches(remaining):
                d_why[dec.session_id].append(f'{a["why"]}, but the pauses before it are enough')
                continue
            dec.action, dec.cause, dec.frozen_since, dec.cause_resets_at = 'freeze', name, now, a['resets_at']
            dec.rate_at_freeze = round(a['rate'] * dec.share, 4)
            remaining -= a['rate'] * dec.share
            first = {'maximizer': 'labelled maximizer: paused first (R39)', 'big': 'labelled big'}.get(kind, f'{dec.window_pct_per_hour:.0f} % of a window per hour')
            dec.reason = f'paused: {a["why"]}; {first}; resumes after {_hhmm(a["resets_at"])}'
            dec.numbers = {k: a.get(k) for k in ('pct', 'rate', 'full_at', 'lockout_min', 'harm', 'cost', 'resets_at')}
            d_trace_meters[name]['frozen'].append(dec.session_id)
        d_trace_meters[name]['remaining_rate'] = remaining

    # --- reasons for everyone left allowed ------------------------------------------------------------------------
    for sid, dec in d_dec.items():
        if dec.reason:
            continue
        if sid in d_not:
            dec.reason = d_not[sid]
        elif sid in d_why:
            dec.reason = '; '.join(dict.fromkeys(d_why[sid])) or 'no lockout ahead'
        else:
            dec.reason = 'no lockout ahead'
        if not dec.numbers:
            dec.numbers = {name: {k: d_assess[name].get(k) for k in ('pct', 'rate', 'full_at', 'lockout_min', 'harm', 'cost')}
                           for name in METERS if d_assess[name].get('lockout_ahead')}

    if trace is not None:
        trace.update(p_need=p_need, jean_active=jean_active, total_usd=round(total_usd, 4), meters=d_trace_meters,
                     candidates={sid: d_why.get(sid) for sid in d_candidates},
                     not_candidates=d_not, released=sorted(released_now))
    return d_dec
