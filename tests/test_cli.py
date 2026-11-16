"""`agent-quota` commands, in process, on temp folders (no tracker: the quota is unknown).
Run: python3 -m unittest discover -s tests"""

import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from agent_quota import cli, store  # noqa: E402


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name, 'home')
        self.env = mock.patch.dict(os.environ, {'AGENT_QUOTA_HOME': str(self.home),
                                                'AGENT_QUOTA_TRACKER': str(Path(self.tmp.name, 'no-tracker'))})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_mode(self):
        self.assertEqual(self.run_cli('mode')[:2], (0, 'observe\n'))
        self.assertEqual(self.run_cli('mode', 'on')[:2], (0, 'on\n'))
        self.assertEqual(store.get_mode(), 'on')
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(['mode', 'sometimes'])

    def test_status_and_json(self):
        store.record_session({'session_id': 'abc123'}, {'AGENT_QUOTA_JOB': 'big'}, time.time())
        code, out, _ = self.run_cli('status')
        self.assertEqual(code, 0)
        self.assertIn('who acts', out)
        self.assertIn('abc123'[:6], out)
        self.assertIn('ERROR', out)            # no tracker: Jean is told (R41)
        code, out, _ = self.run_cli('status', '--json')
        doc = json.loads(out)
        self.assertEqual(doc['decisions_doc']['decisions']['abc123']['action'], 'allow')

    def test_state_json_for_the_maximizer(self):
        code, out, _ = self.run_cli('state', '--json')
        d = json.loads(out)
        self.assertEqual((code, d['who']), (0, 'nobody'))
        self.assertTrue(d['error'])

    def test_decide_forces_a_recompute(self):
        self.run_cli('decide')
        self.run_cli('decide')
        self.assertEqual(len((self.home / 'decisions.jsonl').read_text().splitlines()), 2)

    def test_go_on_and_resume_now(self):
        self.assertEqual(self.run_cli('go-on', 'nobody')[0], 2)
        now = time.time()
        store.write_json(self.home / 'decisions.json', {'ts': now, 'decisions': {'sess-1': {
            'session_id': 'sess-1', 'action': 'freeze', 'reason': 'x', 'cause': 'window',
            'frozen_since': now - 60, 'cause_resets_at': now + 3600}}})
        code, out, _ = self.run_cli('resume-now', 'sess')
        self.assertEqual(code, 0)
        self.assertIn('decision allow', out)
        self.assertEqual(store.load_overrides(now)['sess-1']['kind'], 'resume_now')
        code, out, _ = self.run_cli('go-on', 'sess-1')
        self.assertEqual(store.load_overrides(now)['sess-1']['kind'], 'go_on')


if __name__ == '__main__':
    unittest.main()
