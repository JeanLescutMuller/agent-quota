"""forecast.burn_rate and forecast.project, on the worked examples of protector/CONSIDERATIONS.md §2–3."""
import calendar
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtures  # noqa: F401,E402  (puts src/ on the path)

from agent_quota.forecast import burn_rate, project  # noqa: E402
from agent_quota.reading import WEEK, WINDOW, Meter, Reading  # noqa: E402


def T(s: str) -> int:
    """'2026-11-12 13:00' (UTC) → epoch s."""
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))


def win(ts, pct, reset, machine="mac", week=(40.0, None)):
    """A reading that carries the window (the week fixed, irrelevant to the window's rate)."""
    return Reading(ts, pct, reset, week[0], week[1], "claude_api", machine)


class TestS3(unittest.TestCase):
    """S3: 60 % at 13:00, 1.3 %/min, reset 16:00 → full at 13:31, lockout 2 h 29."""
    reset = T("2026-11-12 16:00")       # the window opened at 11:00

    def test_burn_rate_is_1_3(self):
        # 34 % at 12:30, 60 % at 13:00: slope 26/30 = 0.867 > average 60/120 = 0.5; × 1.5 = 1.3
        l_h = [win(T("2026-11-12 11:40"), 10, self.reset), win(T("2026-11-12 12:30"), 34, self.reset),
               win(T("2026-11-12 12:45"), 47, self.reset), win(T("2026-11-12 13:00"), 60, self.reset)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 1.3, places=9)

    def test_projection(self):
        now = T("2026-11-12 13:00")
        p = project(Meter(WINDOW, 60, self.reset, now, False), 1.3, now)
        self.assertEqual(p.full_at, now + round(40 / 1.3 * 60))                 # 13:30:46
        self.assertEqual(time.strftime("%H:%M", time.gmtime(p.full_at + 30)), "13:31")
        self.assertAlmostEqual(p.lockout_min, (self.reset - p.full_at) / 60)
        self.assertEqual(divmod(int(p.lockout_min), 60), (2, 29))               # 2 h 29
        self.assertEqual(p.rate, 1.3)

    def test_two_machines_and_stale_resends_change_nothing(self):
        # the same S3 history, mixed with the VM's poller lagging (lower values) and resets ±1 s
        r = self.reset
        l_h = [win(T("2026-11-12 11:40"), 10, r), win(T("2026-11-12 12:30"), 34, r - 1, "vm"),
               win(T("2026-11-12 12:40"), 30, r, "vm"), win(T("2026-11-12 12:45"), 47, r + 1),
               win(T("2026-11-12 12:55"), 45, r - 1, "vm"), win(T("2026-11-12 13:00"), 60, r),
               Reading(T("2026-11-12 12:58"), 20, r, 40.0, None, "claude_statusline")]  # a stale re-send
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 1.3, places=9)


class TestS4(unittest.TestCase):
    def test_reset_at_13_40_lockout_9_min(self):
        now, reset = T("2026-11-12 13:00"), T("2026-11-12 13:40")
        p = project(Meter(WINDOW, 60, reset, now, False), 1.3, now)
        self.assertIsNotNone(p.full_at)
        self.assertEqual(int(p.lockout_min), 9)                                 # 13:30:46 → 13:40


class TestS5(unittest.TestCase):
    """Friday 15:00, week at 90 %, reset Monday 19:00, 3 % of the week per hour."""
    now, reset = T("2026-11-13 15:00"), T("2026-11-16 19:00")

    def test_projection(self):
        p = project(Meter(WEEK, 90, self.reset, self.now, False), 3 / 60, self.now)
        self.assertEqual(time.strftime("%a %H:%M", time.gmtime(p.full_at)), "Fri 18:20")
        self.assertAlmostEqual(p.lockout_min, 72 * 60 + 40)                    # ≈ 72 h

    def test_week_burn_rate_whole_percents(self):
        # 87, 88, 89, 90 % every 20 min: 88 % at 14:30 (the step from 14:20), so slope 2/30;
        # average since the week opened (Mon 19:00, 5,520 min) 90/5520 is smaller; × 1.5 = 0.1 %/min
        week = lambda ts, pct: Reading(ts, 0.0, None, pct, self.reset)
        l_h = [week(T("2026-11-13 14:00"), 87), week(T("2026-11-13 14:20"), 88),
               week(T("2026-11-13 14:40"), 89), week(T("2026-11-13 15:00"), 90)]
        self.assertAlmostEqual(burn_rate(l_h, WEEK, self.now), 2 / 30 * 1.5, places=9)


class TestBurnRateEdges(unittest.TestCase):
    def test_reset_inside_the_look_back(self):
        # the old window (reset 13:00) at 90-95 %, the new one opened 13:05 (reset 18:05) at 3 % then 8 %:
        # only the new window counts, from 0 % at 13:05: 8/20 = 0.4 × 1.5 = 0.6, never negative
        old, new = T("2026-11-12 13:00"), T("2026-11-12 18:05")
        l_h = [win(T("2026-11-12 12:20"), 90, old), win(T("2026-11-12 12:50"), 95, old),
               win(T("2026-11-12 13:01"), 0.0, None),                           # rule 8 / no window open
               win(T("2026-11-12 13:10"), 3, new), win(T("2026-11-12 13:20"), 8, new)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:25")), 0.6, places=9)

    def test_fall_over_5_points_is_a_reset_without_reset_times(self):
        # no reset times at all: 90 → 95 → 3 → 8 is a reset at the fall (13:10), the meter re-opened then
        # from 0 %: 8 % in 15 min (13:10 → 13:25) = 0.533 × 1.5
        l_h = [win(T("2026-11-12 12:20"), 90, None), win(T("2026-11-12 12:50"), 95, None),
               win(T("2026-11-12 13:10"), 3, None), win(T("2026-11-12 13:20"), 8, None)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:25")), 8 / 15 * 1.5, places=9)

    def test_week_reset_with_unchanged_reset_time(self):
        # the real 2026-11-13 event: the week went 95 % → 0 % at 17:47 with its reset time unchanged.
        # Around it, stale status line rows: a 95 % dated 17:33 (before the reset, by its ts) and a stale
        # low (59 %) between two 93 %. Only the poller's fall is a reset. Then 0 → 6 % by 18:30.
        reset = T("2026-11-16 19:00")
        wk = lambda s, pct, src="claude_api": Reading(T(s), 0.0, None, pct, reset, src)
        l_h = [wk("2026-11-12 23:15", 93, "claude_statusline"), wk("2026-11-12 23:16", 59, "claude_statusline"),
               wk("2026-11-12 23:17", 93, "claude_statusline"), wk("2026-11-13 17:33", 95, "claude_statusline"),
               wk("2026-11-13 17:45", 95), wk("2026-11-13 17:47", 0), wk("2026-11-13 18:00", 2),
               wk("2026-11-13 18:10", 3, "claude_statusline"), wk("2026-11-13 18:30", 6)]
        now = T("2026-11-13 18:30")
        # base at 18:00 = 2 %: slope 4/30 = 0.133; average since the re-opening 6/43 = 0.140 → 0.140 × 1.5
        self.assertAlmostEqual(burn_rate(l_h, WEEK, now), 6 / 43 * 1.5, places=9)
        # the stale 59 % alone (a status line row) is not a reset: before 17:47 the week reads its 93-95 %
        # (if it were, the week would have re-opened at 23:16 and 93 % in 14 min would read 6.6 %/min)
        mins = (T("2026-11-12 23:30") - (reset - 7 * 86400)) / 60               # since Monday 19:00
        self.assertAlmostEqual(burn_rate(l_h, WEEK, T("2026-11-12 23:30")), 93 / mins * 1.5, places=9)

    def test_status_line_dated_early_is_not_a_reset(self):
        # a session waiting on subagents: its status line row says 59 % dated 12:40 (its last own response),
        # while the poller at 12:45 reads 50 % (truth then): not a reset, the window keeps its readings
        reset = T("2026-11-12 16:00")
        l_h = [win(T("2026-11-12 12:20"), 30, reset), Reading(T("2026-11-12 12:40"), 59, reset, 40.0, None,
               "claude_statusline"), win(T("2026-11-12 12:45"), 50, reset), win(T("2026-11-12 13:00"), 62, reset)]
        # base at 12:30 = 30 %: (62 − 30) / 30 × 1.5
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 32 / 30 * 1.5, places=9)

    def test_fall_of_5_points_or_less_is_not_a_reset(self):
        l_h = [win(T("2026-11-12 12:20"), 50, None), win(T("2026-11-12 12:40"), 46, None),
               win(T("2026-11-12 13:00"), 56, None)]
        # base at 12:30 = 50 (46 is dropped): 6/30 × 1.5
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 6 / 30 * 1.5, places=9)

    def test_passed_reset_reads_zero(self):
        old = T("2026-11-12 13:00")
        l_h = [win(T("2026-11-12 12:20"), 90, old), win(T("2026-11-12 12:50"), 95, old)]
        self.assertEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:30")), 0.0)

    def test_few_points(self):
        reset = T("2026-11-12 16:00")
        self.assertEqual(burn_rate([], WINDOW, T("2026-11-12 13:00")), 0.0)
        # one reading: no slope; the average since 11:00, 60/120 = 0.5 × 1.5
        self.assertAlmostEqual(burn_rate([win(T("2026-11-12 13:00"), 60, reset)], WINDOW, T("2026-11-12 13:00")), 0.75)
        # a window opened 2 min ago at 1 %: the divisor is floored at 10 min, not 2 → 0.1 × 1.5
        self.assertAlmostEqual(burn_rate([win(T("2026-11-12 11:02"), 1, reset)], WINDOW, T("2026-11-12 11:02")), 0.15)

    def test_gap_in_readings_uses_the_span_seen(self):
        # window opened 09:00, readings only from 12:40: slope over 12:40 → 13:00 (20 min), 60 − 50 = 10
        reset = T("2026-11-12 14:00")
        l_h = [win(T("2026-11-12 12:40"), 50, reset), win(T("2026-11-12 13:00"), 60, reset)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 10 / 20 * 1.5, places=9)

    def test_future_readings_ignored(self):
        reset = T("2026-11-12 16:00")
        l_h = [win(T("2026-11-12 12:30"), 34, reset), win(T("2026-11-12 13:00"), 60, reset),
               win(T("2026-11-12 13:30"), 99, reset)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 1.3, places=9)

    def test_stale_no_window_reading_inside_an_open_window_is_dropped(self):
        reset = T("2026-11-12 16:00")
        l_h = [win(T("2026-11-12 12:30"), 34, reset), win(T("2026-11-12 12:50"), 0.0, None),
               win(T("2026-11-12 13:00"), 60, reset)]
        self.assertAlmostEqual(burn_rate(l_h, WINDOW, T("2026-11-12 13:00")), 1.3, places=9)


class TestProjectEdges(unittest.TestCase):
    now, reset = T("2026-11-12 13:00"), T("2026-11-12 16:00")

    def test_no_lockout(self):
        m = Meter(WINDOW, 60, self.reset, self.now, False)
        self.assertIsNone(project(m, 0.0, self.now).full_at)                    # no burn
        self.assertIsNone(project(m, 0.2, self.now).full_at)                    # 100 % at 16:20, after the reset
        self.assertEqual(project(m, 0.2, self.now).lockout_min, 0.0)
        self.assertIsNone(project(Meter(WINDOW, 0.0, None, self.now, False), 5, self.now).full_at)  # no window
        self.assertIsNone(project(Meter(WINDOW, None, None, None, True), 5, self.now).full_at)     # unknown

    def test_already_full(self):
        p = project(Meter(WINDOW, 100, self.reset, self.now, False), 0.0, self.now)
        self.assertEqual((p.full_at, p.lockout_min), (self.now, 180.0))


if __name__ == "__main__":
    unittest.main()
