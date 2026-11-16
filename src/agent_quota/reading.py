"""Reading the quota and the $ from the tracker, read-only (protector/DESIGN.md §1; doc/reading.md).

The tracker's rules (agent-tracker/FOR_READERS.md) followed here:
  - never write: sqlite is opened with `PRAGMA query_only = ON` (never a `mode=ro` URI: macOS refuses it
    intermittently) and `mode=rw`, which never creates a missing file; a busy timeout of 10 s;
  - rule 8: a window (or week) whose reset time has passed reads 0 %, its reset unknown (None);
  - a quota % is account-wide: nothing here gives a session a %.
Every function takes the time it reasons about (`now`, `since_ts`): never the wall clock, so a test or a
replay of the past gets the same answer.
"""
import json
import sqlite3
from dataclasses import dataclass
from urllib.parse import quote

from . import paths
from .config import READING_MAX_AGE_S

WINDOW, WEEK = "window", "week"   # the two meters' names, everywhere in agent-quota
POLLER = "claude_api"             # the tracker's poller rows: the API's answer at `ts`, never a stale re-send


@dataclass(frozen=True)
class Meter:
    """One meter now. pct None = unknown (nothing readable)."""
    name: str                  # WINDOW or WEEK
    pct: float | None          # quota %, 0-100
    resets_at: int | None      # epoch s; None when no window is open (or the week's reset passed, unread)
    reading_ts: int | None     # when the reading was true (the tracker's `ts`)
    stale: bool                # reading older than READING_MAX_AGE_S, or none at all: act on nothing (R41)


@dataclass(frozen=True)
class Meters:
    """Both meters, from the same reading."""
    window: Meter
    week: Meter
    source: str | None = None  # the tracker's `source`: statusline / claude_api / claude_statusline
    machine: str | None = None # the machine that took the reading
    error: str | None = None   # why nothing could be read, for Jean (R41)

    @property
    def stale(self) -> bool:
        return self.window.stale or self.week.stale


@dataclass(frozen=True)
class Reading:
    """One row of the quota history (account_quotas), rule 8 applied at its `ts`."""
    ts: int                        # when the reading was true (the tracker's `ts`)
    window_pct: float | None
    window_resets_at: int | None
    week_pct: float | None
    week_resets_at: int | None
    source: str | None = None      # POLLER, claude_statusline; None in synthetic data (trusted like POLLER)
    machine: str | None = None
    written_ts: int | None = None  # when the tracker wrote it

    def meter(self, name: str) -> tuple[float | None, int | None]:
        """(pct, resets_at) of meter `name`."""
        return (self.window_pct, self.window_resets_at) if name == WINDOW else (self.week_pct, self.week_resets_at)


def _connect(path) -> sqlite3.Connection:
    """Open a tracker database read-only, by its rules. Raises FileNotFoundError when absent (never creates it)."""
    if not path.exists():
        raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{quote(str(path))}?mode=rw", uri=True, timeout=10, isolation_level=None)
    db.execute("PRAGMA busy_timeout = 10000")
    db.execute("PRAGMA query_only = ON")
    return db


def _apply_reset_rule(pct, resets_at, ts):
    """Rule 8: a meter whose reset is at or before `ts` reads 0 %, reset unknown. None pct stays None."""
    if pct is not None and resets_at is not None and resets_at <= ts:
        return 0.0, None
    return (None if pct is None else float(pct)), (None if resets_at is None else int(resets_at))


def read_meters(now: int) -> Meters:
    """The account's two meters at `now`: the freshest reading not after `now`, from quota_latest.json or
    the account_quotas table (both written by the tracker), rule 8 applied at `now`.

    Never raises for missing or broken files: it returns unknown, stale meters with `error` set."""
    d_cand = {}   # source of the candidate -> (ts, source, machine, window (pct, reset), week (pct, reset))
    l_errors = []
    # 1. quota_latest.json: what the status line shows
    try:
        d_q = json.loads((paths.tracker_dir() / "quota_latest.json").read_text())
        fh, sd = d_q.get("five_hour"), d_q.get("seven_day")
        # a null meter in the file = no window open: 0 %, reset unknown (FOR_READERS rule 16)
        win = (fh.get("used_percentage"), fh.get("resets_at")) if fh else (0.0, None)
        week = (sd.get("used_percentage"), sd.get("resets_at")) if sd else (0.0, None)
        if int(d_q["ts"]) <= now:
            d_cand["json"] = (int(d_q["ts"]), d_q.get("source"), d_q.get("machine"), win, week)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        l_errors.append(f"quota_latest.json: {type(e).__name__}: {e}")
    # 2. account_quotas: the same query as the view `latest`, but with raw values and our own `now`
    #    (the view applies rule 8 with sqlite's clock, which a test or a replay must not use)
    try:
        db = _connect(paths.tracker_dir() / "account_quotas.db")
        try:
            row = db.execute(
                "SELECT ts, source, machine, five_hour_pct, five_hour_resets_ts, seven_day_pct, seven_day_resets_ts"
                " FROM account_quotas WHERE (five_hour_pct IS NOT NULL OR seven_day_pct IS NOT NULL) AND ts <= ?"
                " ORDER BY ts DESC, rowid DESC LIMIT 1", (now,)).fetchone()
        finally:
            db.close()
        if row:
            d_cand["db"] = (int(row[0]), row[1], row[2], (row[3], row[4]), (row[5], row[6]))
    except (OSError, sqlite3.Error) as e:
        l_errors.append(f"account_quotas.db: {type(e).__name__}: {e}")

    if not d_cand:
        unknown = lambda name: Meter(name, None, None, None, True)
        return Meters(unknown(WINDOW), unknown(WEEK), error="; ".join(l_errors) or "no quota reading at all")
    # the freshest wins; on a tie the JSON (it is what the status line shows)
    ts, source, machine, win, week = max(d_cand.values(), key=lambda c: c[0])
    stale = now - ts > READING_MAX_AGE_S
    make = lambda name, pr: Meter(name, *_apply_reset_rule(pr[0], pr[1], now), ts, stale)
    return Meters(make(WINDOW, win), make(WEEK, week), source, machine)


def meter_history(since_ts: int, until_ts: int | None = None) -> list[Reading]:
    """Every quota reading with since_ts <= ts (<= until_ts), oldest first, keyed by the tracker's `ts`.

    With `until_ts` (a replay), only rows already written by then (written_ts <= until_ts): no look-ahead.
    Keyed by `ts` (the tracker's rule 10), not by `written_ts`: a status line can re-send a reading days
    old with a fresh `written_ts` (a week at 80 % written on Sunday, taken on Thursday before a reset).
    The price: a status line row's `ts` is its session's last main-thread response, so a session waiting on
    its subagents dates 55 %... 59 % at the same `ts`, up to 15 min early (doc/reading.md §3).
    Rule 8 per row; nothing else is cleaned (stale re-sends, two machines): forecast does that.
    Raises FileNotFoundError / sqlite3.Error when the database cannot be read."""
    db = _connect(paths.tracker_dir() / "account_quotas.db")
    try:
        sql = ("SELECT ts, written_ts, source, machine, five_hour_pct, five_hour_resets_ts, seven_day_pct, seven_day_resets_ts"
               " FROM account_quotas WHERE ts >= ? AND (five_hour_pct IS NOT NULL OR seven_day_pct IS NOT NULL)")
        params = (since_ts,)
        if until_ts is not None:
            sql, params = sql + " AND ts <= ? AND written_ts <= ?", (since_ts, until_ts, until_ts)
        l_rows = db.execute(sql + " ORDER BY ts, rowid", params).fetchall()
    finally:
        db.close()
    return [Reading(int(ts), *_apply_reset_rule(w_pct, w_reset, ts), *_apply_reset_rule(k_pct, k_reset, ts),
                    source, machine, written_ts)
            for ts, written_ts, source, machine, w_pct, w_reset, k_pct, k_reset in l_rows]


def session_usd(since_ts: int, until_ts: int) -> dict[str, float]:
    """$ per session id (Claude Code's own list-price figure, never a bill) of this machine's API requests
    with since_ts <= ts < until_ts, from `telemetry` in sessions_usages.db. A session's subagents carry its
    session id, so they are counted in it. Each request once (Claude Code re-sends batches): the same
    dedup as the view `telemetry_requests`, restricted to the time range first (the view scans the whole
    table: 0.95 s against 0.004 s, measured 2026-11-16). Returns {} when the database does not exist."""
    try:
        db = _connect(paths.tracker_dir() / "sessions_usages.db")
    except FileNotFoundError:
        return {}
    try:
        l_rows = db.execute(
            "SELECT session_id, SUM(cost_usd) FROM telemetry WHERE rowid IN"
            " (SELECT MIN(rowid) FROM telemetry WHERE event = 'api_request' AND request_id IS NOT NULL"
            "  AND ts >= ? AND ts < ? GROUP BY request_id)"
            " AND session_id IS NOT NULL AND cost_usd IS NOT NULL GROUP BY session_id", (since_ts, until_ts)).fetchall()
    finally:
        db.close()
    return {sid: float(usd) for sid, usd in l_rows}
