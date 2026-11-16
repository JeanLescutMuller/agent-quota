"""A fake tracker data folder in a temp dir, with the real files' shapes (checked 2026-11-16 against
~/opt/agent-tracker/data/claude: doc/reading.md). Sets $AGENT_QUOTA_TRACKER to it; `close()` restores.

    with FakeTracker() as tr:
        tr.quota_latest(ts, 60, reset_5h, 40, reset_7d)
        tr.quota_row(ts, 60, reset_5h, 40, reset_7d, written_ts=ts + 30)
        tr.request(ts, "session-a", 1.25)
"""
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from . import _SRC  # noqa: F401  (puts src/ on the path)

# the tracker's own DDL, trimmed of comments (account_quotas.db, sessions_usages.db)
_ACCOUNT_DDL = """
CREATE TABLE account_quotas (ts INTEGER NOT NULL, dt TEXT NOT NULL, source TEXT NOT NULL, five_hour_pct REAL,
    five_hour_resets_ts INTEGER, seven_day_pct REAL, seven_day_resets_ts INTEGER, observed_by_session TEXT,
    written_ts INTEGER NOT NULL, raw TEXT NOT NULL, row_hash TEXT NOT NULL UNIQUE, machine TEXT);
CREATE INDEX account_quotas_ts ON account_quotas(ts);
CREATE INDEX account_quotas_written ON account_quotas(written_ts);
CREATE VIEW latest AS
    SELECT ts, dt, source, machine,
           CASE WHEN five_hour_resets_ts <= CAST(strftime('%s', 'now') AS INTEGER) THEN 0.0 ELSE five_hour_pct END AS five_hour_pct,
           CASE WHEN five_hour_resets_ts <= CAST(strftime('%s', 'now') AS INTEGER) THEN NULL ELSE five_hour_resets_ts END AS five_hour_resets_ts,
           CASE WHEN seven_day_resets_ts <= CAST(strftime('%s', 'now') AS INTEGER) THEN 0.0 ELSE seven_day_pct END AS seven_day_pct,
           CASE WHEN seven_day_resets_ts <= CAST(strftime('%s', 'now') AS INTEGER) THEN NULL ELSE seven_day_resets_ts END AS seven_day_resets_ts
    FROM (SELECT * FROM account_quotas WHERE five_hour_pct IS NOT NULL OR seven_day_pct IS NOT NULL
          ORDER BY ts DESC, rowid DESC LIMIT 1);
"""
_SESSIONS_DDL = """
CREATE TABLE telemetry (ts INTEGER NOT NULL, dt TEXT NOT NULL, event TEXT NOT NULL, session_id TEXT, request_id TEXT,
    model TEXT, query_source TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER, cost_usd REAL, received_ts INTEGER, raw TEXT NOT NULL, row_hash TEXT NOT NULL UNIQUE);
CREATE INDEX telemetry_ts ON telemetry(ts);
CREATE VIEW telemetry_requests AS SELECT * FROM telemetry WHERE rowid IN (SELECT MIN(rowid) FROM telemetry
    WHERE event = 'api_request' AND request_id IS NOT NULL GROUP BY request_id);
"""


def _dt(ts):
    import datetime as _d
    return _d.datetime.fromtimestamp(ts, _d.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeTracker:
    def __init__(self, with_dbs: bool = True):
        self._tmp = tempfile.TemporaryDirectory(prefix="aq-tracker-")
        self.dir = Path(self._tmp.name)
        self._old_env = os.environ.get("AGENT_QUOTA_TRACKER")
        os.environ["AGENT_QUOTA_TRACKER"] = str(self.dir)
        self._n = 0
        if with_dbs:
            for name, ddl in (("account_quotas.db", _ACCOUNT_DDL), ("sessions_usages.db", _SESSIONS_DDL)):
                db = sqlite3.connect(self.dir / name)
                db.executescript(ddl)
                db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._old_env is None:
            os.environ.pop("AGENT_QUOTA_TRACKER", None)
        else:
            os.environ["AGENT_QUOTA_TRACKER"] = self._old_env
        self._tmp.cleanup()

    def quota_latest(self, ts, w_pct, w_reset, k_pct, k_reset, source="statusline", machine="mac"):
        """quota_latest.json; w_pct None writes a null five_hour (k_pct None: a null seven_day)."""
        d = {"ts": ts, "dt": _dt(ts), "source": source, "machine": machine,
             "five_hour": None if w_pct is None else {"used_percentage": w_pct, "resets_at": w_reset},
             "seven_day": None if k_pct is None else {"used_percentage": k_pct, "resets_at": k_reset}}
        (self.dir / "quota_latest.json").write_text(json.dumps(d))

    def quota_row(self, ts, w_pct, w_reset, k_pct, k_reset, written_ts=None, source="claude_api", machine="mac"):
        """One row of account_quotas."""
        self._n += 1
        db = sqlite3.connect(self.dir / "account_quotas.db")
        db.execute("INSERT INTO account_quotas VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (ts, _dt(ts), source, w_pct, w_reset, k_pct, k_reset, None, written_ts or ts, "{}",
                    f"h{self._n}", machine))
        db.commit()
        db.close()

    def request(self, ts, session_id, usd, request_id=None, event="api_request", copies=1):
        """One API request in telemetry; `copies` > 1 re-sends it (same request_id), as Claude Code does."""
        self._n += 1
        rid = request_id or f"req_{self._n}"
        db = sqlite3.connect(self.dir / "sessions_usages.db")
        for c in range(copies):
            db.execute("INSERT INTO telemetry (ts, dt, event, session_id, request_id, cost_usd, received_ts, raw, row_hash)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", (ts, _dt(ts), event, session_id, rid, usd, ts + c, "{}",
                                                      f"t{self._n}_{c}"))
        db.commit()
        db.close()
