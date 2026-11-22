"""The hook as Claude Code runs it: `bin/agent-quota hook` as a subprocess, JSON on stdin, on temp folders.
Fails open on garbage; mode off and observe never hold; a freeze in mode on holds until resume-now, an allow
decision or a mode change; SIGTERM (Esc) exits 0 and is logged. Run: python3 -m unittest discover -s tests"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.pop("CLAUDE_ACCOUNT", None)   # the session's account (my-setup's claude-account) never leaks into a test

ROOT = Path(__file__).resolve().parent.parent
BIN = str(ROOT / 'bin' / 'agent-quota')
SID = 'sess-freeze-1'


def rc(p):
    """Wait for a hook process, close its pipes, return its exit code."""
    return finish(p)[0]


def finish(p):
    """Wait for a hook process, read and close its pipes: (exit code, stdout)."""
    p.wait(timeout=10)
    out = p.stdout.read()
    p.stdout.close()
    p.stderr.close()
    return p.returncode, out


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.notify_log = t / 'home', t / 'notify.log'
        notify = t / 'notify.sh'
        notify.write_text(f'#!/bin/sh\necho "$@" >> {self.notify_log}\n')
        notify.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('AGENT_QUOTA_', 'CLAUDE_CODE_')) and k != 'TMUX'}
        self.env.update(AGENT_QUOTA_HOME=str(self.home), AGENT_QUOTA_TRACKER=str(t / 'no-tracker'),
                        AGENT_QUOTA_NOTIFY=str(notify), AGENT_QUOTA_NO_CAFFEINATE='1',
                        AGENT_QUOTA_HOLD_POLL_S='0.3', AGENT_QUOTA_OVERRIDE_POLL_S='0.1',
                        AGENT_QUOTA_DECISION_MAX_AGE_S='3600', CLAUDE_CODE_ENTRYPOINT='sdk-cli')

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, BIN, *args], env=self.env, capture_output=True, text=True, timeout=30)

    def start_hook(self, payload):
        p = subprocess.Popen([sys.executable, BIN, 'hook'], env=self.env, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p.stdin.write(payload if isinstance(payload, str) else json.dumps(payload))
        p.stdin.close()
        return p

    def write_freeze(self, action='freeze', scope='all'):
        now = time.time()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / 'decisions.json').write_text(json.dumps({'ts': now, 'decisions': {SID: {
            'session_id': SID, 'action': action, 'scope': scope, 'reason': 'test freeze', 'cause': 'window',
            'frozen_since': now, 'cause_resets_at': now + 3600}}}))

    def wait_held(self, p):
        # held = still running, and hook.log says hold_start
        deadline = time.time() + 10
        while time.time() < deadline:
            if (self.home / 'hook.log').exists() and 'hold_start' in (self.home / 'hook.log').read_text():
                break
            self.assertIsNone(p.poll(), 'the hook exited instead of holding')
            time.sleep(0.05)
        time.sleep(0.3)
        self.assertIsNone(p.poll())

    def payload(self):
        return {'session_id': SID, 'agent_id': 'sub1', 'tool_name': 'Bash', 'cwd': '/tmp', 'hook_event_name': 'PreToolUse'}

    # --- fail open --------------------------------------------------------------------------------------------
    def test_garbage_input_fails_open(self):
        for raw in ('not json', '', '[1,2]', '{"no_session": 1}'):
            p = self.start_hook(raw)
            self.assertEqual(finish(p), (0, ''))
        self.assertEqual(len((self.home / 'hook-errors.log').read_text().splitlines()), 4)

    def test_unwritable_home_fails_open(self):
        Path(self.tmp.name, 'a-file').write_text('x')
        self.env['AGENT_QUOTA_HOME'] = str(Path(self.tmp.name, 'a-file', 'home'))
        p = self.start_hook(self.payload())
        self.assertEqual(rc(p), 0)

    # --- modes ------------------------------------------------------------------------------------------------
    def test_mode_off_does_nothing(self):
        self.home.mkdir(parents=True)
        (self.home / 'mode').write_text('off\n')
        self.write_freeze()
        self.assertEqual(rc(self.start_hook(self.payload())), 0)
        self.assertFalse((self.home / 'sessions').exists())

    def test_observe_records_and_never_holds(self):
        self.write_freeze()
        t0 = time.time()
        self.assertEqual(rc(self.start_hook(self.payload())), 0)
        self.assertLess(time.time() - t0, 5)
        s = json.loads((self.home / 'sessions' / f'{SID}.json').read_text())
        self.assertEqual((s['agent_ids'], s['cwd'], s['interactive']), (['sub1'], '/tmp', False))
        self.assertFalse(self.notify_log.exists())

    # --- the freeze -------------------------------------------------------------------------------------------
    def test_freeze_released_by_resume_now(self):
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook(self.payload())
        self.wait_held(p)
        r = self.cli('resume-now', SID[:8])
        self.assertEqual(r.returncode, 0, r.stderr)
        t0 = time.time()
        self.assertEqual(rc(p), 0)
        self.assertLess(time.time() - t0, 3)
        log = (self.home / 'hook.log').read_text()
        self.assertIn('hold_end', log)
        self.assertEqual(self.notify_log.read_text().split('\n')[:2], ['event WaitingForUser', 'event Working'])
        # the next call is not held: the override stands and the decision is allow
        self.assertEqual(json.loads((self.home / 'decisions.json').read_text())['decisions'][SID]['action'], 'allow')
        self.assertEqual(rc(self.start_hook(self.payload())), 0)

    def test_freeze_released_by_an_allow_decision(self):
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook(self.payload())
        self.wait_held(p)
        self.write_freeze(action='allow')
        self.assertEqual(rc(p), 0)

    def test_freeze_released_by_mode_observe(self):
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook(self.payload())
        self.wait_held(p)
        self.cli('mode', 'observe')
        self.assertEqual(rc(p), 0)

    def test_scope_subagents_holds_only_subagents_calls(self):
        # v1.1: an interactive session frozen in its subagents only: Jean's main thread (no agent_id, or an empty
        # one) always passes at once; a subagent's call (agent_id set) is held until the decision allows it
        self.cli('mode', 'on')
        self.write_freeze(scope='subagents')
        for main in ({'session_id': SID, 'tool_name': 'Bash'}, {'session_id': SID, 'agent_id': '', 'tool_name': 'Bash'}):
            t0 = time.time()
            self.assertEqual(rc(self.start_hook(main)), 0)
            self.assertLess(time.time() - t0, 5)
        self.assertFalse((self.home / 'hook.log').exists() and 'hold_start' in (self.home / 'hook.log').read_text())
        p = self.start_hook(self.payload())          # agent_id 'sub1'
        self.wait_held(p)
        self.write_freeze(action='allow')
        self.assertEqual(rc(p), 0)

    def test_scope_all_holds_the_main_thread(self):
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook({'session_id': SID, 'tool_name': 'Bash'})
        self.wait_held(p)
        self.write_freeze(action='allow')
        self.assertEqual(rc(p), 0)

    def test_notified_once_per_freeze(self):
        self.cli('mode', 'on')
        self.write_freeze()
        l_p = [self.start_hook(self.payload()) for _ in range(2)]
        for p in l_p:
            self.wait_held(p)
        self.write_freeze(action='allow')
        for p in l_p:
            self.assertEqual(rc(p), 0)
        self.assertEqual(self.notify_log.read_text().count('WaitingForUser'), 1)

    def test_sigterm_esc_exits_0_and_is_logged(self):
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook(self.payload())
        self.wait_held(p)
        p.send_signal(signal.SIGTERM)
        self.assertEqual(rc(p), 0)
        self.assertIn('cancelled by Jean (Esc)', (self.home / 'hook.log').read_text())
        line = json.loads((self.home / 'decisions.jsonl').read_text().splitlines()[-1])
        self.assertEqual((line['event'], line['session']), ('hold_cancelled', SID))


    @unittest.skipUnless(os.path.exists('/usr/bin/caffeinate'), 'no caffeinate on this machine')
    def test_keeps_the_mac_awake_while_holding(self):
        del self.env['AGENT_QUOTA_NO_CAFFEINATE']
        self.cli('mode', 'on')
        self.write_freeze()
        p = self.start_hook(self.payload())
        self.wait_held(p)
        pattern = f'caffeinate -i -w {p.pid}'
        self.assertEqual(subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode, 0)
        self.write_freeze(action='allow')
        self.assertEqual(rc(p), 0)
        deadline = time.time() + 5   # caffeinate -w notices its process is gone within a moment
        while time.time() < deadline and subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode == 0:
            time.sleep(0.1)
        self.assertNotEqual(subprocess.run(['pgrep', '-f', pattern], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
