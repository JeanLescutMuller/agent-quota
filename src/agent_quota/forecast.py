"""Burn rate and projection of a meter (protector/DESIGN.md §1, §3). Pure: no file, no clock.

burn rate (% of the meter per minute) = max(recent slope, average since the meter opened) × RATE_FACTOR
    recent slope : (pct now − pct L ago) ÷ L, with L = RECENT_MIN (30 min) for a window, WEEK_RECENT_H (48 h) for
                   the week (with 30 min the week said "lockout ahead" on 51 % of minutes and was right once:
                   Jean front-loads the week; doc/replay.md §6)
    average      : pct now ÷ minutes since the window opened (week: since the week opened),
                   the divisor floored at MIN_RATE_DENOMINATOR_MIN
The legacy maximizer's rule, measured best on Pro (doc/prior_work.md §3). The average keeps an ordinary
pause from reading as zero; the slope reacts to a burst.

Worked example (CONSIDERATIONS S3): at 13:00 the window is at 60 %, it was at 34 % at 12:30, it resets at
16:00 (opened 11:00): slope 26 ÷ 30 = 0.867, average 60 ÷ 120 = 0.5 → 0.867 × 1.5 = 1.3 %/min;
full at 13:00 + 40 ÷ 1.3 = 13:30:46, lockout 16:00 − 13:30:46 = 149 min (2 h 29).
"""
from dataclasses import dataclass

from .config import (MIN_RATE_DENOMINATOR_MIN, RATE_FACTOR, RECENT_MIN, RESET_FALL_PCT, RESET_TOLERANCE_S,
                     WEEK_RECENT_H, WEEK_S, WINDOW_S)
from .reading import POLLER, WINDOW, Meter, Reading


@dataclass(frozen=True)
class Projection:
    """Where a meter goes at its burn rate."""
    full_at: int | None        # epoch s when it reaches 100 %; None when not before its reset (or unknown)
    lockout_min: float         # minutes from full_at to the reset; 0 when full_at is None
    rate: float = 0.0          # the burn rate used, % per minute


def _steps(l_history: list[Reading], meter_name: str, now: int) -> tuple[list[tuple[int, float]], int | None]:
    """The current window's (or week's) readings, cleaned: ([(ts, pct)] the first reading of each new
    running maximum, oldest first; the time it opened, or None when unknown).

    Cleaning (agent-tracker doc/tables.md §7.2, rule 10), checked on the real history (doc/reading.md §4):
      - a window is known by its reset time (±RESET_TOLERANCE_S: sources differ by 1 s); the current one is
        named by the newest reading that knows a reset; readings before it opened, or of another, are dropped;
      - within it the % only rises, so a lower reading is a stale re-send (a status line showing 59 % of
        the week between two 93 %) or the other machine lagging: dropped (running maximum);
      - except a reset: the poller reading more than RESET_FALL_PCT points below the poller's own running
        maximum (with no reset time at all: any reading below the running maximum). The week was reset from 95 % to 0 % on
        Friday 2026-11-13 17:47 UTC with its reset time unchanged."""
    duration = WINDOW_S if meter_name == WINDOW else WEEK_S
    l_pts = sorted(((r.ts, *r.meter(meter_name), r.source) for r in l_history
                    if r.ts <= now and r.meter(meter_name)[0] is not None), key=lambda p: p[0])  # stable, by ts
    if not l_pts:
        return [], None
    l_resets = [p[2] for p in l_pts if p[2] is not None]
    cur_reset = l_resets[-1] if l_resets else None
    if cur_reset is not None and cur_reset <= now:
        return [], None                                    # it has reset since: 0 %, nothing known after
    opened = cur_reset - duration if cur_reset is not None else None
    if opened is not None:
        # this window's own readings: from its opening, with its reset (a no-window reading inside a known
        # open window contradicts it: a stale one, dropped)
        l_pts = [p for p in l_pts if p[0] >= opened - RESET_TOLERANCE_S
                 and p[2] is not None and abs(p[2] - cur_reset) <= RESET_TOLERANCE_S]
    l_steps, top, top_trusted = [], None, None   # running max of all readings / of the trusted ones
    for ts, pct, reset, source in l_pts:
        # trusted: the poller's readings (API answers, true at their ts: they only rise between resets,
        # across both machines), any reading in synthetic data (no source) or when no reset time is known.
        # A status line row is never trusted for a fall: its ts can be 15 min early, so a poller reading
        # can be well below it with no reset in between
        trusted = cur_reset is None or source in (None, POLLER)
        if trusted and top_trusted is not None and pct < top_trusted - RESET_FALL_PCT:
            l_steps, top, top_trusted = [], None, None     # a reset: start again from this reading,
            opened = ts                                    # the meter re-opened then, from 0 %
        if trusted:
            top_trusted = pct if top_trusted is None else max(top_trusted, pct)
        if top is None or pct > top:
            l_steps.append((ts, pct))
            top = pct
    return l_steps, opened


def burn_rate(l_history: list[Reading], meter_name: str, now: int) -> float:
    """Burn rate of meter `meter_name` (WINDOW or WEEK) at `now`, in % of that meter per minute, ≥ 0.

    `l_history`: meter_history(now − WEEK_S): the week's average then starts at a mid-week reset if one
    happened (8,500 rows, 0.07 s on the real files, 2026-11-16); a window alone needs only 6 h. Robust to whole-% readings, a reset inside the look-back (the old window's
    readings are ignored, never a negative rate), few points, and two machines' readings mixed."""
    l_steps, opened = _steps(l_history, meter_name, now)
    if not l_steps:
        return 0.0
    pct_now = l_steps[-1][1]
    recent_min = RECENT_MIN if meter_name == WINDOW else WEEK_RECENT_H * 60
    t0 = now - recent_min * 60
    floor_div = lambda seconds: max(seconds / 60.0, MIN_RATE_DENOMINATOR_MIN)
    # 1. recent slope over the last recent_min
    l_before = [s for s in l_steps if s[0] <= t0]
    if l_before:
        slope = (pct_now - l_before[-1][1]) / recent_min   # the value it had recent_min ago
    elif opened is not None and opened >= t0:
        slope = pct_now / floor_div(now - opened)          # opened inside the look-back, from 0 %
    else:
        # few points: nothing before the look-back, so the slope over the span actually seen
        # (a single point gives 0; the average below then decides)
        ts_first, pct_first = l_steps[0]
        slope = (pct_now - pct_first) / floor_div(now - ts_first)
    # 2. average since the window (week) opened, from 0 %
    average = pct_now / floor_div(now - opened) if opened is not None else 0.0
    return max(slope, average, 0.0) * RATE_FACTOR


def project(meter: Meter, rate: float, now: int) -> Projection:
    """When `meter` reaches 100 % at `rate` (% per minute), and the lockout that follows until its reset.

    full_at None (no lockout ahead) when the rate is 0, the % or the reset is unknown, or 100 % comes at or
    after the reset. A meter already at 100 % is full now."""
    if meter.pct is None or meter.resets_at is None or meter.resets_at <= now:
        return Projection(None, 0.0, rate)
    if meter.pct >= 100:
        full_at = now
    elif rate <= 0:
        return Projection(None, 0.0, rate)
    else:
        full_at = now + round((100 - meter.pct) / rate * 60)
    if full_at >= meter.resets_at:
        return Projection(None, 0.0, rate)
    return Projection(full_at, (meter.resets_at - full_at) / 60.0, rate)
