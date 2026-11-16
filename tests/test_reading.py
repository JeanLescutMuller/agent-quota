"""reading: read_meters, meter_history, session_usd on a fake tracker; one smoke test on the real one."""
import calendar
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.tracker import FakeTracker  # noqa: E402  (also puts src/ on the path)

from agent_quota import paths, reading, state  # noqa: E402
from agent_quota.reading import WEEK, WINDOW, meter_history, read_meters, session_usd, session_usd_split  # noqa: E402


def T(s: str) -> int:
    return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M"))


NOW = T("2026-11-12 13:00")
W_RESET, K_RESET = T("2026-11-12 16:00"), T("2026-11-16 19:00")


class TestPaths(unittest.TestCase):
    def test_env_overrides(self):
        old = {k: os.environ.get(k) for k in ("AGENT_QUOTA_HOME", "AGENT_QUOTA_TRACKER")}
        try:
            os.environ["AGENT_QUOTA_HOME"], os.environ["AGENT_QUOTA_TRACKER"] = "/x/home", "/x/tracker"
            self.assertEqual((str(paths.home()), str(paths.tracker_dir())), ("/x/home", "/x/tracker"))
            for k in old:
                os.environ.pop(k)
            self.assertEqual(paths.home(), Path.home() / "opt/agent-quota/state")
            self.assertEqual(paths.tracker_dir(), Path.home() / "opt/agent-tracker/data/claude")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class TestReadMeters(unittest.TestCase):
    def setUp(self):
        self.tr = FakeTracker()

    def tearDown(self):
        self.tr.close()

    def test_fresh_json(self):
        self.tr.quota_latest(NOW - 30, 60, W_RESET, 40, K_RESET)
        m = read_meters(NOW)
        self.assertEqual((m.window.pct, m.window.resets_at, m.week.pct, m.week.resets_at), (60, W_RESET, 40, K_RESET))
        self.assertEqual((m.window.name, m.week.name, m.window.reading_ts), (WINDOW, WEEK, NOW - 30))
        self.assertFalse(m.stale)
        self.assertIsNone(m.error)

    def test_stale(self):
        self.tr.quota_latest(NOW - 601, 60, W_RESET, 40, K_RESET)
        m = read_meters(NOW)
        self.assertTrue(m.window.stale and m.week.stale and m.stale)
        self.tr.quota_latest(NOW - 600, 60, W_RESET, 40, K_RESET)
        self.assertFalse(read_meters(NOW).stale)                                # exactly 600 s: still fresh

    def test_passed_reset_reads_zero(self):
        self.tr.quota_latest(NOW - 30, 97, NOW - 10, 40, K_RESET)               # the window reset 10 s ago
        m = read_meters(NOW)
        self.assertEqual((m.window.pct, m.window.resets_at), (0.0, None))
        self.assertEqual(m.week.pct, 40)
        m = read_meters(K_RESET + 60)                                           # the week too, 1 min after its reset
        self.assertEqual((m.week.pct, m.week.resets_at), (0.0, None))

    def test_null_window_in_json(self):
        self.tr.quota_latest(NOW - 30, None, None, 40, K_RESET)
        self.assertEqual((read_meters(NOW).window.pct, read_meters(NOW).window.resets_at), (0.0, None))

    def test_db_when_json_missing_or_older(self):
        self.tr.quota_row(NOW - 100, 61, W_RESET, 41, K_RESET, source="claude_api", machine="vm")
        m = read_meters(NOW)
        self.assertEqual((m.window.pct, m.source, m.machine), (61, "claude_api", "vm"))
        self.tr.quota_latest(NOW - 200, 60, W_RESET, 40, K_RESET)               # older than the db's row
        self.assertEqual(read_meters(NOW).window.pct, 61)
        self.tr.quota_latest(NOW - 50, 62, W_RESET, 41, K_RESET)                # fresher
        self.assertEqual(read_meters(NOW).window.pct, 62)

    def test_readings_after_now_ignored(self):
        # a replay of the past must not see the future
        self.tr.quota_row(NOW - 100, 61, W_RESET, 41, K_RESET)
        self.tr.quota_row(NOW + 100, 70, W_RESET, 42, K_RESET)
        self.tr.quota_latest(NOW + 100, 70, W_RESET, 42, K_RESET)
        self.assertEqual(read_meters(NOW).window.pct, 61)


class TestNothingToRead(unittest.TestCase):
    def test_unknown_and_creates_nothing(self):
        with FakeTracker(with_dbs=False) as tr:
            m = read_meters(NOW)
            self.assertIsNone(m.window.pct)
            self.assertTrue(m.stale)
            self.assertIn("quota_latest.json", m.error)
            self.assertEqual(session_usd(NOW - 1800, NOW), {})
            with self.assertRaises(FileNotFoundError):
                meter_history(NOW - 3600)
            self.assertEqual(list(tr.dir.iterdir()), [])                         # never creates a tracker file
            # and the shared check lets nobody act on it (R41)
            self.assertEqual(state.shared_check(m, [], NOW).who, state.NOBODY)


class TestMeterHistory(unittest.TestCase):
    def setUp(self):
        self.tr = FakeTracker()

    def tearDown(self):
        self.tr.close()

    def test_keyed_by_ts_and_no_look_ahead(self):
        # a status line row: ts = the session's last main-thread response (12:00), written at 12:20
        self.tr.quota_row(T("2026-11-12 12:00"), 59, W_RESET, 40, K_RESET, written_ts=T("2026-11-12 12:20"),
                          source="claude_statusline")
        self.tr.quota_row(T("2026-11-12 12:10"), 57, W_RESET - 1, 40, K_RESET - 1, source="claude_api", machine="vm")
        l_h = meter_history(T("2026-11-12 11:00"))
        self.assertEqual([(r.ts, r.window_pct, r.machine, r.written_ts) for r in l_h],
                         [(T("2026-11-12 12:00"), 59, "mac", T("2026-11-12 12:20")),
                          (T("2026-11-12 12:10"), 57, "vm", T("2026-11-12 12:10"))])
        self.assertEqual(len(meter_history(T("2026-11-12 12:05"))), 1)
        # a replay at 12:15 does not see the row written at 12:20
        self.assertEqual([r.machine for r in meter_history(T("2026-11-12 11:00"), until_ts=T("2026-11-12 12:15"))], ["vm"])

    def test_rule_8_per_row(self):
        old = T("2026-11-12 11:00")
        self.tr.quota_row(T("2026-11-12 11:01"), 95, old, 40, K_RESET)          # its window had reset
        self.tr.quota_row(T("2026-11-12 11:30"), 5, W_RESET, 41, K_RESET)
        l_h = meter_history(T("2026-11-12 10:00"))
        self.assertEqual([(r.window_pct, r.window_resets_at) for r in l_h], [(0.0, None), (5, W_RESET)])
        self.assertEqual(l_h[0].meter(WEEK), (40, K_RESET))


class TestSessionUsd(unittest.TestCase):
    def test_sum_dedup_and_range(self):
        with FakeTracker() as tr:
            tr.request(NOW - 600, "a", 1.0, copies=3)                           # one request sent 3 times: $1
            tr.request(NOW - 300, "a", 0.5)
            tr.request(NOW - 200, "b", 2.0)
            tr.request(NOW - 100, None, 9.0)                                   # no session id: not counted
            tr.request(NOW - 100, "b", 9.0, event="api_error")                 # not a request
            tr.request(NOW - 3600, "a", 9.0)                                   # before the range
            tr.request(NOW, "a", 9.0)                                          # until_ts is excluded
            self.assertEqual(session_usd(NOW - 1800, NOW), {"a": 1.5, "b": 2.0})

    def test_split_main_and_subagents(self):
        with FakeTracker() as tr:
            tr.request(NOW - 600, "a", 1.0)                                                   # Jean's main thread
            tr.request(NOW - 500, "a", 2.0, query_source="agent:builtin:general-purpose", copies=2)  # its subagent, once
            tr.request(NOW - 400, "a", 0.5, query_source="agent:builtin:Plan")
            tr.request(NOW - 300, "a", 0.25, query_source="agent_summary")                    # not a subagent's
            tr.request(NOW - 200, "b", 3.0, query_source="sdk")                               # a script
            self.assertEqual(session_usd_split(NOW - 1800, NOW), {"a": (1.25, 2.5), "b": (3.0, 0.0)})
            self.assertEqual(session_usd(NOW - 1800, NOW), {"a": 3.75, "b": 3.0})


@unittest.skipUnless((Path.home() / "opt/agent-tracker/data/claude/account_quotas.db").exists(),
                     "the real tracker's files are not on this machine")
class TestRealTrackerSmoke(unittest.TestCase):
    """Read-only, on ~/opt/agent-tracker/data/claude: the code runs on the real shapes."""

    def test_real_files(self):
        old = os.environ.pop("AGENT_QUOTA_TRACKER", None)
        try:
            now = int(time.time())
            m = read_meters(now)
            self.assertIsNone(m.error)
            for meter in (m.window, m.week):
                self.assertTrue(meter.pct is None or 0 <= meter.pct <= 100)
            l_h = meter_history(now - 6 * 3600)
            self.assertTrue(all(isinstance(r, reading.Reading) for r in l_h))
            self.assertEqual([r.ts for r in l_h], sorted(r.ts for r in l_h))
            d_usd = session_usd(now - 1800, now)
            self.assertTrue(all(v >= 0 for v in d_usd.values()))
            c = state.shared_check(m, l_h, now)
            self.assertIn(c.who, (state.PROTECTOR, state.MAXIMIZER, state.NOBODY))
        finally:
            if old is not None:
                os.environ["AGENT_QUOTA_TRACKER"] = old


if __name__ == "__main__":
    unittest.main()
