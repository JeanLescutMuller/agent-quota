"""Test helpers. Importing this package puts the repo's src/ on sys.path, so tests import agent_quota, and unsets
$CLAUDE_ACCOUNT (a session on account b made 12 tests fail, 2026-11-22)."""
import os
import sys
from pathlib import Path

os.environ.pop("CLAUDE_ACCOUNT", None)   # the session's account (my-setup's claude-account) never leaks into a test

_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
