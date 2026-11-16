"""state: spare quota, meter states, who acts (R1), the shared check end to end."""
import calendar
import itertools
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtures  # noqa: F401,E402  (puts src/ on the path)

from agent_quota import state  # noqa: E402
from agent_quota.forecast import Projection  # noqa: E402
from agent_quota.reading import WEEK, WINDOW, Meter, Meters, Reading  # noqa: E402
from agent_quota.state import (LOCKOUT_AHEAD, MAXIMIZER, NOBODY, NORMAL, PROTECTOR, SPARE, STALE,  # noqa: E402
                               meter_state, shared_check, week_spare_pct, who_acts)


def T(s: str) -> int:
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))


WEEK_RESET = T("2026-11-16 19:00")   # a Monday, 19:00 UTC


class TestWeekSpare(unittest.TestCase):
    """maximizer/DESIGN.md §2's worked example, in % of the week (one window = 13.2 %)."""

    def test_thursday_no_spare(self):
        now = T("2026-11-12 19:00")                                            # 96 h to the reset
        spare = week_spare_pct(Meter(WEEK, 40, WEEK_RESET, now, False), now)
        self.assertAlmostEqual(spare, 60 - 96 / 5 * 13.2)                      # −193.44 %
        self.assertLess(spare, 0)

    def test_monday_spare(self):
        now = T("2026-11-16 15:00")                                            # 4 h to the reset
        spare = week_spare_pct(Meter(WEEK, 70, WEEK_RESET, now, False), now)
        self.assertAlmostEqual(spare, 19.44)                                   # 30 − 0.8 × 13.2
        self.assertAlmostEqual(spare / 100 * 1469, 286, delta=1)               # ≈ $286 in the design's $

    def test_unknown(self):
        now = T("2026-11-16 15:00")
        self.assertIsNone(week_spare_pct(Meter(WEEK, 0.0, None, now, False), now))
        self.assertIsNone(week_spare_pct(Meter(WEEK, None, None, None, True), now))


class TestMeterState(unittest.TestCase):
    now = T("2026-11-16 15:00")
    full = Projection(T("2026-11-16 16:00"), 120.0, 1.0)
    none = Projection(None, 0.0, 0.1)

    def test_states(self):
        w = Meter(WINDOW, 60, T("2026-11-16 18:00"), self.now, False)
        k = Meter(WEEK, 70, WEEK_RESET, self.now, False)
        self.assertEqual(meter_state(w, self.full), LOCKOUT_AHEAD)
        self.assertEqual(meter_state(w, self.none), NORMAL)
        self.assertEqual(meter_state(w, self.none, 50.0), NORMAL)              # the window never yields spare (R4)
        self.assertEqual(meter_state(k, self.none, 19.44), SPARE)
        self.assertEqual(meter_state(k, self.none, -3.0), NORMAL)
        self.assertEqual(meter_state(k, self.none, None), NORMAL)
        self.assertEqual(meter_state(k, self.full, 19.44), LOCKOUT_AHEAD)      # spare and lockout ahead: lockout wins

    def test_stale_is_unknown(self):
        self.assertEqual(meter_state(Meter(WINDOW, 60, T("2026-11-16 18:00"), self.now - 900, True), self.full), STALE)
        self.assertEqual(meter_state(Meter(WEEK, None, None, None, True), self.none, 19.0), STALE)


class TestWhoActs(unittest.TestCase):
    """R1: every combination of the two meters' states gives exactly one actor."""
    expected = {  # (window, week) → who
        (LOCKOUT_AHEAD, LOCKOUT_AHEAD): PROTECTOR, (LOCKOUT_AHEAD, NORMAL): PROTECTOR,
        (LOCKOUT_AHEAD, SPARE): PROTECTOR,         (LOCKOUT_AHEAD, STALE): NOBODY,
        (NORMAL, LOCKOUT_AHEAD): PROTECTOR,        (NORMAL, NORMAL): NOBODY,
        (NORMAL, SPARE): MAXIMIZER,                (NORMAL, STALE): NOBODY,
        (SPARE, LOCKOUT_AHEAD): PROTECTOR,         (SPARE, NORMAL): NOBODY,       # a window's spare is ignored (R4)
        (SPARE, SPARE): MAXIMIZER,                 (SPARE, STALE): NOBODY,
        (STALE, LOCKOUT_AHEAD): NOBODY,          (STALE, NORMAL): NOBODY,
        (STALE, SPARE): NOBODY,                  (STALE, STALE): NOBODY,
    }

    def test_truth_table(self):
        l_states = [LOCKOUT_AHEAD, NORMAL, SPARE, STALE]
        self.assertEqual(set(self.expected), set(itertools.product(l_states, l_states)))
        for (w, k), who in self.expected.items():
            with self.subTest(window=w, week=k):
                self.assertEqual(who_acts(w, k), who)

    def test_never_both(self):
        # the maximizer acts only when no meter has lockout ahead and none is unknown
        for w, k in itertools.product([LOCKOUT_AHEAD, NORMAL, SPARE, STALE], repeat=2):
            who = who_acts(w, k)
            self.assertIn(who, (PROTECTOR, MAXIMIZER, NOBODY))
            if who == MAXIMIZER:
                self.assertNotIn(LOCKOUT_AHEAD, (w, k))
                self.assertNotIn(STALE, (w, k))


class TestSharedCheck(unittest.TestCase):
    def test_s3_protector(self):
        # S3 on a Thursday: the window has lockout ahead, the week is normal → protector
        now, w_reset = T("2026-11-12 13:00"), T("2026-11-12 16:00")
        # the week at 25 % since Monday 19:00: 25 / 3,960 min × 1.5 → 100 % in 132 h, after its reset (102 h)
        l_h = [Reading(T("2026-11-12 12:30"), 34, w_reset, 25, WEEK_RESET),
               Reading(now, 60, w_reset, 25, WEEK_RESET)]
        m = Meters(Meter(WINDOW, 60, w_reset, now, False), Meter(WEEK, 25, WEEK_RESET, now, False))
        c = shared_check(m, l_h, now)
        self.assertEqual((c.window_state, c.week_state, c.who), (LOCKOUT_AHEAD, NORMAL, PROTECTOR))
        self.assertAlmostEqual(c.window.rate, 1.3, places=9)
        self.assertEqual(int(c.window.lockout_min), 149)

    def test_monday_spare_maximizer(self):
        # Monday 15:00, week 70 %, barely moving; the window at 10 %, slow → maximizer
        now, w_reset = T("2026-11-16 15:00"), T("2026-11-16 18:00")
        l_h = [Reading(T("2026-11-16 14:00"), 8, w_reset, 70, WEEK_RESET), Reading(now, 10, w_reset, 70, WEEK_RESET)]
        m = Meters(Meter(WINDOW, 10, w_reset, now, False), Meter(WEEK, 70, WEEK_RESET, now, False))
        c = shared_check(m, l_h, now)
        self.assertEqual((c.window_state, c.week_state, c.who), (NORMAL, SPARE, MAXIMIZER))
        self.assertAlmostEqual(c.week_spare_pct, 19.44)

    def test_spare_week_but_window_lockout_ahead(self):
        # the week would lose quota, but the window is about to hit 100 %: the protector, not the maximizer
        now, w_reset = T("2026-11-16 15:00"), T("2026-11-16 18:00")
        l_h = [Reading(T("2026-11-16 14:30"), 60, w_reset, 70, WEEK_RESET), Reading(now, 90, w_reset, 70, WEEK_RESET)]
        m = Meters(Meter(WINDOW, 90, w_reset, now, False), Meter(WEEK, 70, WEEK_RESET, now, False))
        self.assertEqual(shared_check(m, l_h, now).who, PROTECTOR)

    def test_stale_nobody(self):
        now, w_reset = T("2026-11-12 13:00"), T("2026-11-12 16:00")
        l_h = [Reading(T("2026-11-12 12:30"), 34, w_reset, 40, WEEK_RESET), Reading(now - 900, 60, w_reset, 41, WEEK_RESET)]
        m = Meters(Meter(WINDOW, 60, w_reset, now - 900, True), Meter(WEEK, 41, WEEK_RESET, now - 900, True))
        self.assertEqual(shared_check(m, l_h, now).who, NOBODY)


if __name__ == "__main__":
    unittest.main()
