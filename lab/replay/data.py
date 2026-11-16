"""Load Jean's quota history and per-session $ from the tracker, read-only, and clean them.

Reads (never writes, tracker rules FOR_READERS.md §1-11: PRAGMA query_only, never mode=ro):
    /Users/jeanlescut/opt/agent-tracker/data/claude/account_quotas.db   table account_quotas
    /Users/jeanlescut/opt/agent-tracker/data/claude/sessions_usages.db  table telemetry (Mac only)
Writes (cache, gitignored):
    lab/replay/out/readings.pkl   one row per accepted reading: ts, dt, meter, pct, resets_ts
    lab/replay/out/reading_ts.npy every reading's time (any value): for the reading's age
    lab/replay/out/requests.pkl   one row per api_request / api_error: ts, dt, session_id, query_source, prompt_id, usd, status

Run: python3 lab/replay/data.py   (prints a short summary)
"""
import json
import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

TRACKER = Path(os.environ.get("AGENT_QUOTA_TRACKER", "/Users/jeanlescut/opt/agent-tracker/data/claude"))
OUT = Path(__file__).resolve().parent / "out"
MAX5X_TS = 1791391860  # 2026-10-07 16:51 UTC: Pro -> Max 5x (tracker rule 11: never mix the plans)
METER_LEN_S = {"window": 5 * 3600, "week": 7 * 86400}


def _connect(name):
    db = sqlite3.connect(TRACKER / name, timeout=10)
    db.execute("PRAGMA query_only = ON")
    return db


def clean_meter(df_raw, meter):
    """One meter's readings -> the accepted series (ts, pct, resets_ts).

    Rules applied, in order:
    - a reset time is rounded to the minute (readings jitter by 1 s: 12:39:59 vs 12:40:00);
    - a reading whose reset is more than one meter length ahead is stale (re-sent by a statusline long after);
    - a reading whose reset is older than the current one is stale (tracker rule 10);
    - within one reset key the % never decreases (rule 10), EXCEPT a drop that the next readings confirm
      (a fall of >= 10 points and every reading of the same key in the next 15 min (>= 3 of them) <= the new value + 2;
      a statusline re-sending an old value flaps up and down, a real reset stays down): the week was reset early by Anthropic
      on 2026-11-13 with its reset time unchanged, which only such a confirmed drop can show.
    """
    col_pct, col_rst = {"window": ("five_hour_pct", "five_hour_resets_ts"),
                        "week": ("seven_day_pct", "seven_day_resets_ts")}[meter]
    df = df_raw[["ts", col_pct, col_rst]].rename(columns={col_pct: "pct", col_rst: "resets_ts"}).copy()
    df = df.dropna(subset=["pct"])
    df["resets_ts"] = (df["resets_ts"] / 60).round() * 60
    # no reset time = no window open: the meter is at 0 (it carries pct 0 in the data)
    ok = df["resets_ts"].isna() | ((df["resets_ts"] - df["ts"] <= METER_LEN_S[meter] + 120) & (df["resets_ts"] > df["ts"] - 60))
    df = df[ok].sort_values("ts").reset_index(drop=True)
    a_pct, a_rst, a_ts = df["pct"].to_numpy(), df["resets_ts"].to_numpy(), df["ts"].to_numpy()
    l_keep, level, key = [], -1.0, None
    for i in range(len(df)):
        v, r = a_pct[i], a_rst[i]
        if pd.isna(r):
            # no open window: accept as 0 only once the previous key has passed (else a stale empty reading)
            if key is None or a_ts[i] >= key:
                l_keep.append(i); level, key = 0.0, None
            continue
        if key is None or r > key:
            l_keep.append(i); level, key = v, r
        elif r < key:
            continue  # an older window's reading, re-sent late
        elif v >= level:
            if v > level:
                l_keep.append(i)
            level = v
        else:
            # a drop within the same key: real only if the following readings confirm it
            j_end = int(np.searchsorted(a_ts, a_ts[i] + 900, side="right"))
            l_next = [a_pct[j] for j in range(i + 1, j_end) if a_rst[j] == r]
            if level - v >= 10 and len(l_next) >= 3 and max(l_next) <= v + 2:
                l_keep.append(i); level = v
    out = df.loc[l_keep, ["ts", "pct", "resets_ts"]].copy()
    out["meter"] = meter
    return out


def load(refresh=False):
    """-> (df_readings, df_requests), from the cache unless refresh."""
    OUT.mkdir(exist_ok=True)
    p_read, p_req = OUT / "readings.pkl", OUT / "requests.pkl"
    if p_read.exists() and p_req.exists() and not refresh:
        return pd.read_pickle(p_read), pd.read_pickle(p_req)
    with _connect("account_quotas.db") as db:
        df_raw = pd.read_sql(
            "SELECT ts, written_ts, source, machine, five_hour_pct, five_hour_resets_ts, seven_day_pct, seven_day_resets_ts "
            "FROM account_quotas WHERE ts >= ? AND source IN ('claude_statusline', 'claude_api') ORDER BY ts",
            db, params=(MAX5X_TS,))
    # A statusline row's ts is the session's last API response, but its % can be fresher (a long turn
    # re-renders it): its write time matches the poller's readings better (median gap 6 vs 11 points over
    # the rows written > 10 min late). Use the write time; drop the rows written > 1 day late (backfills).
    lag = df_raw["written_ts"] - df_raw["ts"]
    df_raw = df_raw[lag <= 86400].copy()
    df_raw["ts"] = df_raw["written_ts"].where(df_raw["source"] == "claude_statusline", df_raw["ts"])
    df_raw = df_raw.sort_values("ts")
    # every valid reading time (the cleaned series keeps only changes): how old the freshest reading is
    np.save(OUT / "reading_ts.npy", np.sort(df_raw["ts"].to_numpy()))
    df_read = pd.concat([clean_meter(df_raw, "window"), clean_meter(df_raw, "week")], ignore_index=True)
    df_read.insert(1, "dt", pd.to_datetime(df_read["ts"], unit="s", utc=True))
    df_read = df_read[["ts", "dt", "meter", "pct", "resets_ts"]].sort_values(["meter", "ts"]).reset_index(drop=True)
    # per-request $ on this Mac (the VM's telemetry is on the VM: never seen here)
    with _connect("sessions_usages.db") as db:
        l_rows = db.execute(
            "SELECT ts, event, session_id, query_source, cost_usd, raw FROM telemetry "
            "WHERE ts >= ? AND event IN ('api_request', 'api_error') ORDER BY ts", (MAX5X_TS - 86400,)).fetchall()
    l_req = []
    for ts, event, sid, qs, usd, raw in l_rows:
        d_attr = json.loads(raw).get("attributes", {})
        l_req.append((ts, sid, qs, d_attr.get("prompt.id"), usd or 0.0,
                      str(d_attr.get("status_code")) if event == "api_error" else "ok"))
    df_req = pd.DataFrame(l_req, columns=["ts", "session_id", "query_source", "prompt_id", "usd", "status"])
    df_req.insert(1, "dt", pd.to_datetime(df_req["ts"], unit="s", utc=True))
    df_read.to_pickle(p_read)
    df_req.to_pickle(p_req)
    return df_read, df_req


if __name__ == "__main__":
    df_read, df_req = load(refresh=True)
    print(df_read.groupby("meter").agg(n=("ts", "size"), first=("dt", "min"), last=("dt", "max"), max_pct=("pct", "max")))
    print(df_req.groupby("status").agg(n=("ts", "size"), usd=("usd", "sum")))
