"""store.py: the state files, the sessions registry, mode, overrides, the lock, and the recompute end to end on a fake
tracker (temp AGENT_QUOTA_HOME and AGENT_QUOTA_TRACKER). Run: python3 -m unittest discover -s tests"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from agent_quota import store  # noqa: E402


def make_tracker(folder, now, window_steps, window_reset_in_s, week_pct=40, week_reset_in_s=3 * 86400, usd=None):
    """A fake tracker folder: quota_latest.json, account_quotas.db, sessions_usages.db (telemetry).
    window_steps: [(seconds before now, window %)], oldest first; usd: {session_id: $ in the last 10 min}."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    w_reset, k_reset = int(now + window_reset_in_s), int(now + week_reset_in_s)
    db = sqlite3.connect(folder / 'account_quotas.db')
    db.execute('CREATE TABLE account_quotas (ts INTEGER, written_ts INTEGER, source TEXT, machine TEXT,'
               ' five_hour_pct REAL, five_hour_resets_ts INTEGER, seven_day_pct REAL, seven_day_resets_ts INTEGER)')
    for ago, pct in window_steps:
        t = int(now - ago)
        db.execute('INSERT INTO account_quotas VALUES (?,?,?,?,?,?,?,?)',
                   (t, t, 'statusline', 'test', pct, w_reset, week_pct, k_reset))
    db.commit()
    db.close()
    last_ago, last_pct = window_steps[-1]
    (folder / 'quota_latest.json').write_text(json.dumps({
        'ts': int(now - last_ago), 'source': 'statusline', 'machine': 'test',
        'five_hour': {'used_percentage': last_pct, 'resets_at': w_reset},
        'seven_day': {'used_percentage': week_pct, 'resets_at': k_reset}}))
    db = sqlite3.connect(folder / 'sessions_usages.db')
    db.execute('CREATE TABLE telemetry (ts INTEGER, session_id TEXT, event TEXT, request_id TEXT, cost_usd REAL)')
    for i, (sid, dollars) in enumerate((usd or {}).items()):
        db.execute('INSERT INTO telemetry VALUES (?,?,?,?,?)', (int(now - 600), sid, 'api_request', f'r{i}', dollars))
    db.commit()
    db.close()


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home, self.tracker = Path(self.tmp.name, 'home'), Path(self.tmp.name, 'tracker')
        self.env = mock.patch.dict(os.environ, {'AGENT_QUOTA_HOME': str(self.home),
                                                'AGENT_QUOTA_TRACKER': str(self.tracker)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class Sessions(TempHome):
    def test_record_session(self):
        env = {'AGENT_QUOTA_JOB': 'BIG:3', 'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}
        s = store.record_session({'session_id': 's1', 'cwd': '/x'}, env, 100.0)
        s = store.record_session({'session_id': 's1', 'agent_id': 'a1', 'cwd': '/x'}, env, 200.0)
        s = store.record_session({'session_id': 's1', 'agent_id': 'a1'}, env, 300.0)
        self.assertEqual((s['label'], s['interactive'], s['first_ts'], s['last_ts'], s['calls'], s['agent_ids'], s['cwd']),
                         ('big:3', False, 100.0, 300.0, 3, ['a1'], '/x'))
        self.assertEqual(store.load_sessions()['s1']['calls'], 3)
        self.assertEqual(store.load_sessions(since_ts=301), {})

    def test_interactive(self):
        self.assertTrue(store.is_interactive({'CLAUDE_CODE_ENTRYPOINT': 'cli'}))
        self.assertFalse(store.is_interactive({'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}))
        self.assertFalse(store.is_interactive({}))
        self.assertFalse(store.is_interactive({'CLAUDE_CODE_ENTRYPOINT': 'cli', 'CLAUDE_CODE_SESSION_ATTENDED': '0'}))

    def test_no_session_id_and_odd_ids(self):
        self.assertIsNone(store.record_session({}, {}, 1.0))
        store.record_session({'session_id': '../evil/id'}, {}, 1.0)
        self.assertEqual(list(store.load_sessions()), ['../evil/id'])
        self.assertTrue(all(p.parent.name == 'sessions' for p in self.home.rglob('*.json')))

    def test_resolve_session(self):
        for sid in ('abc111', 'abc222', 'xyz'):
            store.record_session({'session_id': sid}, {}, 1.0)
        self.assertEqual(store.resolve_session('xy'), 'xyz')
        with self.assertRaises(ValueError):
            store.resolve_session('abc')
        with self.assertRaises(ValueError):
            store.resolve_session('nope')


class ModeOverridesLock(TempHome):
    def test_mode(self):
        self.assertEqual(store.get_mode(), 'observe')
        store.set_mode('on')
        self.assertEqual(store.get_mode(), 'on')
        with self.assertRaises(ValueError):
            store.set_mode('maybe')
        (self.home / 'mode').write_text('garbage')
        self.assertEqual(store.get_mode(), 'observe')

    def test_overrides_expire(self):
        store.set_override('a', 'go_on', 200.0, 100.0)
        store.set_override('b', 'resume_now', 400.0, 300.0)   # the write at 300 drops a (expired)
        self.assertEqual(set(store.load_overrides()), {'b'})
        self.assertEqual(store.load_overrides(500.0), {})

    def test_lock_is_non_blocking(self):
        with store.recompute_lock() as first:
            with store.recompute_lock() as second:
                self.assertEqual((first, second), (True, False))
        with store.recompute_lock() as again:
            self.assertTrue(again)

    def test_whole_file_writes_leave_no_temp(self):
        store.write_json(self.home / 'x.json', {'a': 1})
        store.write_json(self.home / 'x.json', {'a': 2})
        self.assertEqual(json.loads((self.home / 'x.json').read_text()), {'a': 2})
        self.assertEqual([p.name for p in self.home.iterdir()], ['x.json'])


class Recompute(TempHome):
    def setUp(self):
        super().setUp()
        self.now = time.time()
        # the window climbed 1 % per minute for an hour, 92 % now, reset in 60 min; the job spent $10 locally
        steps = [(3600 - 300 * i, 32 + 5 * i) for i in range(12)] + [(30, 92)]
        make_tracker(self.tracker, self.now, steps, 3600, usd={'job': 10.0})
        store.record_session({'session_id': 'job', 'cwd': '/w'}, {'CLAUDE_CODE_ENTRYPOINT': 'sdk-cli'}, self.now - 20)

    def test_end_to_end_freeze_and_log(self):
        doc = store.recompute(self.now)
        self.assertIsNone(doc['error'])
        self.assertEqual(doc['shared_state']['who'], 'protector')
        self.assertEqual(doc['decisions']['job']['action'], 'freeze', doc['decisions']['job']['reason'])
        line = json.loads((self.home / 'decisions.jsonl').read_text().splitlines()[-1])
        self.assertTrue(line['trace']['meters']['window']['act'])
        self.assertEqual(line['trace']['meters']['window']['frozen'], ['job'])
        self.assertIn('job', line['usd_by_session'])
        self.assertIn('would pause 1', (self.home / 'statusline.txt').read_text())   # mode observe
        store.set_mode('on')
        store.recompute(self.now + 61)
        self.assertIn('⏸ 1 paused', (self.home / 'statusline.txt').read_text())

    def test_fresh_decisions_are_reused(self):
        doc = store.recompute(self.now)
        self.assertEqual(store.recompute(self.now + 10)['ts'], doc['ts'])
        self.assertNotEqual(store.recompute(self.now + 10, force=True)['ts'], doc['ts'])
        self.assertEqual(len((self.home / 'decisions.jsonl').read_text().splitlines()), 2)

    def test_lock_held_elsewhere_uses_existing(self):
        doc = store.recompute(self.now)
        with store.recompute_lock():
            self.assertEqual(store.recompute(self.now + 120)['ts'], doc['ts'])

    def test_tracker_unreadable_keeps_freezes(self):
        store.recompute(self.now)
        os.environ['AGENT_QUOTA_TRACKER'] = str(Path(self.tmp.name, 'missing'))
        doc = store.recompute(self.now + 120)
        self.assertTrue(doc['error'])
        self.assertEqual(doc['decisions']['job']['action'], 'freeze')
        self.assertIn('quota not visible', (self.home / 'statusline.txt').read_text())


if __name__ == '__main__':
    unittest.main()
