"""Where agent-quota keeps its state and where it reads the tracker (protector/DESIGN.md §1).

Both are read from the environment at every call, so a test sets the variable and gets its own folders.
Nothing here creates a folder: the writers (store.py) do.
"""
import os
from pathlib import Path


def home() -> Path:
    """agent-quota's own state folder: $AGENT_QUOTA_HOME, default ~/opt/agent-quota/state."""
    return Path(os.environ.get("AGENT_QUOTA_HOME") or "~/opt/agent-quota/state").expanduser()


def tracker_dir() -> Path:
    """The tracker's Claude data folder, read-only: $AGENT_QUOTA_TRACKER, default ~/opt/agent-tracker/data/claude.

    Holds quota_latest.json, account_quotas.db, sessions_usages.db (doc/reading.md)."""
    return Path(os.environ.get("AGENT_QUOTA_TRACKER") or "~/opt/agent-tracker/data/claude").expanduser()
