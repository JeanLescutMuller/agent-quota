"""Test helpers. Importing this package puts the repo's src/ on sys.path, so tests import agent_quota."""
import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
