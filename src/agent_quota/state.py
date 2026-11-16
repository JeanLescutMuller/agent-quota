"""The shared check (R1, R2, R4, R5): which half may act. protector/DESIGN.md §3. Pure.

for each meter (window, week):
    lockout ahead ⇔ project(meter, burn_rate).full_at is not None   (100 % before the reset)
week only:
    windows_left = hours to the week's reset ÷ 5
    spare_pct    = (100 − week_pct) − windows_left × WINDOW_SHARE_OF_WEEK_PCT
    spare quota  ⇔ spare_pct > 0 and not lockout ahead
who acts: a meter stale (no fresh reading) → nobody · lockout ahead on either → protector ·
          else week spare quota → maximizer · else nobody

One function returns one state per meter and one actor, so the protector and the maximizer can never
both act (R1). The window never yields spare quota (R4): what a window leaves is not lost while the week
is the limit.

Worked example (maximizer/DESIGN.md §2, in %): Monday 15:00 UTC, week at 70 %, reset at 19:00:
spare = 30 − (4 ÷ 5) × 13.2 = 30 − 10.56 = 19.44 % of the week (≈ $286); Thursday 19:00, 40 %, 96 h left:
60 − 19.2 × 13.2 = −193.44 → no spare quota.
"""
from dataclasses import dataclass

from . import forecast
from .config import WINDOW_SHARE_OF_WEEK_PCT
from .reading import WEEK, WINDOW, Meter, Meters, Reading

# the four states of a meter, and the three answers of who_acts
LOCKOUT_AHEAD, NORMAL, SPARE, STALE = "lockout ahead", "normal", "spare quota", "stale"
PROTECTOR, MAXIMIZER, NOBODY = "protector", "maximizer", "nobody"


def week_spare_pct(week: Meter, now: int) -> float | None:
    """Spare quota of the week, in % of the week (> 0: some would be lost at the reset even if every window
    left were used in full). None when the week's % or reset is unknown."""
    if week.pct is None or week.resets_at is None or week.resets_at <= now:
        return None
    windows_left = (week.resets_at - now) / 3600 / 5
    return (100 - week.pct) - windows_left * WINDOW_SHARE_OF_WEEK_PCT


def meter_state(meter: Meter, projection: forecast.Projection, spare_pct: float | None = None) -> str:
    """One of LOCKOUT_AHEAD, NORMAL, SPARE, STALE for one meter.

    `spare_pct`: week_spare_pct() for the week; leave None for the window (it never yields spare quota).
    A stale or unreadable meter is STALE: nobody acts on it (R41). (Not "unknown": that word is the vocabulary's quota no record explains.)"""
    if meter.stale or meter.pct is None:
        return STALE
    if projection.full_at is not None:
        return LOCKOUT_AHEAD
    if meter.name == WEEK and spare_pct is not None and spare_pct > 0:
        return SPARE
    return NORMAL


def who_acts(window_state: str, week_state: str) -> str:
    """PROTECTOR, MAXIMIZER or NOBODY: exactly one, from the two meters' states (R1).

    | window        | week          | who acts  |
    | stale         | any           | nobody    |  (never pause, never spend, on a stale number)
    | any           | stale         | nobody    |
    | lockout ahead | any           | protector |
    | any           | lockout ahead | protector |
    | other         | spare quota   | maximizer |  (the window's own SPARE, if passed, is ignored: R4)
    | other         | other         | nobody    |"""
    if STALE in (window_state, week_state):
        return NOBODY
    if LOCKOUT_AHEAD in (window_state, week_state):
        return PROTECTOR
    if week_state == SPARE:
        return MAXIMIZER
    return NOBODY


@dataclass(frozen=True)
class SharedCheck:
    """The whole shared check at one moment: what `agent-quota state --json` can print for the maximizer."""
    now: int
    window_state: str
    week_state: str
    who: str
    window: forecast.Projection
    week: forecast.Projection
    week_spare_pct: float | None


def shared_check(meters: Meters, l_history: list[Reading], now: int) -> SharedCheck:
    """Runs §3 end to end on already-read meters and history: one copy of the check for both halves."""
    p_win = forecast.project(meters.window, forecast.burn_rate(l_history, WINDOW, now), now)
    p_week = forecast.project(meters.week, forecast.burn_rate(l_history, WEEK, now), now)
    spare = week_spare_pct(meters.week, now)
    s_win, s_week = meter_state(meters.window, p_win), meter_state(meters.week, p_week, spare)
    return SharedCheck(now, s_win, s_week, who_acts(s_win, s_week), p_win, p_week, spare)
