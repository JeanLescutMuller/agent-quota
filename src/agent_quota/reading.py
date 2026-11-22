"""Reading the quota and the $ from the tracker, read-only (protector/DESIGN.md §1; doc/reading.md).

The tracker's rules (agent-tracker/FOR_READERS.md) followed here:
  - never write: sqlite is opened with `PRAGMA query_only = ON` (never a `mode=ro` URI: macOS refuses it
    intermittently) and `mode=rw`, which never creates a missing file; a busy timeout of 10 s;
  - rule 8: a window (or week) whose reset time has passed reads 0 %, its reset unknown (None);
  - a quota % is account-wide: nothing here gives a session a %;
  - several Claude accounts (2026-11-19, tracker FOR_READERS rule 19): a session reads ITS account's quota, from its
    $CLAUDE_ACCOUNT (unset, outside my-setup's wrapper: the account with the most room left): quota_latest.<name>.json
    and the rows of that account.
Every function takes the time it reasons about (`now`, `since_ts`): never the wall clock, so a test or a
replay of the past gets the same answer.
"""
import json
import os
import re
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


def _best_account(now: int | None) -> str:
    """The account with the most room left among the tracker's quota_latest.<name>.json files: room = 100 - max(5h %, 7d %), rule 8
    applied at `now` (None: not applied); a tie: the first name; no file: `a` (a machine with one account, as before 2026-11-19)."""
    l_rooms = []
    try:
        for p in sorted(paths.tracker_dir().glob("quota_latest.*.json")):
            name = p.name[len("quota_latest."):-len(".json")]
            if not re.fullmatch(r"[a-z0-9_-]+", name):
                continue
            try:
                d = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            l_pcts = []
            for k in ("five_hour", "seven_day"):
                w = d.get(k) or {}
                resets = w.get("resets_at")
                l_pcts.append(0 if now is not None and isinstance(resets, (int, float)) and resets <= now else (w.get("used_percentage") or 0))
            l_rooms.append((max(l_pcts), name))
    except (OSError, AttributeError, TypeError):
        pass
    return min(l_rooms)[1] if l_rooms else "a"


def account_name(now: int | None = None) -> str:
    """The session's Claude account: $CLAUDE_ACCOUNT (set by my-setup's claude-account); without it (a session started outside
    the wrapper, or a bad name): the account with the most room left."""
    name = os.environ.get("CLAUDE_ACCOUNT") or ""
    return name if re.fullmatch(r"[a-z0-9_-]+", name) else _best_account(now)


def _account_where(db, now: int | None = None) -> tuple[str, tuple] | None:
    """The SQL (starting with ' AND') that limits account_quotas to the session's account, and its parameters;
    None when this database cannot answer for that account (another account, a tracker from before 2026-11-19)."""
    name = account_name(now)
    if "account" not in {r[1] for r in db.execute("PRAGMA table_info(account_quotas)")}:
        return ("", ()) if name == "a" else None      # before 2026-11-19 there was one account, named a
    if name == "a":   # readings with no account (before 2026-11-19, one account) belong to the account named a
        return " AND (account IS NULL OR account = (SELECT org_uuid FROM accounts WHERE name = 'a'))", ()
    return " AND account = (SELECT org_uuid FROM accounts WHERE name = ?)", (name,)


def _apply_reset_rule(pct, resets_at, ts):
    """Rule 8: a meter whose reset is at or before `ts` reads 0 %, reset unknown. None pct stays None."""
    if pct is not None and resets_at is not None and resets_at <= ts:
        return 0.0, None
    return (None if pct is None else float(pct)), (None if resets_at is None else int(resets_at))


def read_meters(now: int) -> Meters:
    """The account's two meters at `now`: the freshest reading not after `now`, from quota_latest.<name>.json or
    the account_quotas table (both written by the tracker), rule 8 applied at `now`.

    Never raises for missing or broken files: it returns unknown, stale meters with `error` set."""
    d_cand = {}   # source of the candidate -> (ts, source, machine, window (pct, reset), week (pct, reset))
    l_errors = []
    # 1. quota_latest.<name>.json: what the status line shows
    try:
        name = account_name(now)
        d_q = json.loads((paths.tracker_dir() / f"quota_latest.{name}.json").read_text())
        fh, sd = d_q.get("five_hour"), d_q.get("seven_day")
        # a null meter in the file = no window open: 0 %, reset unknown (FOR_READERS rule 16)
        win = (fh.get("used_percentage"), fh.get("resets_at")) if fh else (0.0, None)
        week = (sd.get("used_percentage"), sd.get("resets_at")) if sd else (0.0, None)
        if int(d_q["ts"]) <= now:
            d_cand["json"] = (int(d_q["ts"]), d_q.get("source"), d_q.get("machine"), win, week)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        l_errors.append(f"quota_latest.<name>.json: {type(e).__name__}: {e}")
    # 2. account_quotas: the same query as the view `latest`, but with raw values and our own `now`
    #    (the view applies rule 8 with sqlite's clock, which a test or a replay must not use)
    try:
        db = _connect(paths.tracker_dir() / "account_quotas.db")
        try:
            where = _account_where(db, now)
            row = None if where is None else db.execute(
                "SELECT ts, source, machine, five_hour_pct, five_hour_resets_ts, seven_day_pct, seven_day_resets_ts"
                " FROM account_quotas WHERE (five_hour_pct IS NOT NULL OR seven_day_pct IS NOT NULL) AND ts <= ?"
                + where[0] + " ORDER BY ts DESC, rowid DESC LIMIT 1", (now, *where[1])).fetchone()
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
        where = _account_where(db)
        l_rows = [] if where is None else db.execute(sql + where[0] + " ORDER BY ts, rowid", (*params, *where[1])).fetchall()
    finally:
        db.close()
    return [Reading(int(ts), *_apply_reset_rule(w_pct, w_reset, ts), *_apply_reset_rule(k_pct, k_reset, ts),
                    source, machine, written_ts)
            for ts, written_ts, source, machine, w_pct, w_reset, k_pct, k_reset in l_rows]


def session_usd_split(since_ts: int, until_ts: int) -> dict[str, tuple[float, float]]:
    """{session_id: (main_usd, subagent_usd)}: $ (Claude Code's own list-price figure, never a bill) of this
    machine's API requests with since_ts <= ts < until_ts, from `telemetry` in sessions_usages.db, split by who
    made them. A session's subagents carry its session id; their requests are told apart by `query_source`
    `agent:<kind>:<name>` (`agent:builtin:general-purpose`, `agent:builtin:Plan`…; seen on the Mac,
    2026-11-16); everything else (`repl_main_thread`, `sdk`, `compact`, `agent_summary`…) is the main thread's.
    Each request once (Claude Code re-sends batches): the same dedup as the view `telemetry_requests`,
    restricted to the time range first (the view scans the whole table: 0.95 s against 0.004 s, measured
    2026-11-16). Returns {} when the database does not exist."""
    try:
        db = _connect(paths.tracker_dir() / "sessions_usages.db")
    except FileNotFoundError:
        return {}
    try:
        l_rows = db.execute(
            "SELECT session_id, SUM(CASE WHEN query_source LIKE 'agent:%' THEN 0 ELSE cost_usd END),"
            " SUM(CASE WHEN query_source LIKE 'agent:%' THEN cost_usd ELSE 0 END) FROM telemetry WHERE rowid IN"
            " (SELECT MIN(rowid) FROM telemetry WHERE event = 'api_request' AND request_id IS NOT NULL"
            "  AND ts >= ? AND ts < ? GROUP BY request_id)"
            " AND session_id IS NOT NULL AND cost_usd IS NOT NULL GROUP BY session_id", (since_ts, until_ts)).fetchall()
    finally:
        db.close()
    return {sid: (float(main or 0), float(sub or 0)) for sid, main, sub in l_rows}


def session_usd(since_ts: int, until_ts: int) -> dict[str, float]:
    """$ per session id, its subagents counted in it: session_usd_split's two parts summed."""
    return {sid: main + sub for sid, (main, sub) in session_usd_split(since_ts, until_ts).items()}
