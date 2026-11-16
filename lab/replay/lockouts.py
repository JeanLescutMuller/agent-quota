"""Every lockout that actually happened on Max 5x: a window or the week at >= 100 % before its reset.

Reads: lab/replay/out/readings.pkl, requests.pkl (data.py), and the names of the transcript files under
       /Users/jeanlescut/.claude/projects/ (folder name only = the session's project; contents never read).
Writes: lab/replay/out/lockouts.csv (one row per lockout), out/lockouts.log (the printed tables).

Run: python3 lab/replay/lockouts.py > lab/replay/out/lockouts.log
"""
from pathlib import Path

import pandas as pd

import data

THRESH = 100        # a lockout = the meter at 100 %: Claude Code answers 429 until the reset
NEAR = 99           # also listed: windows that reached 99 % (one request away)
ACTIVE_MIN = 30     # DESIGN §2: "Jean active" = typed in an interactive session in the last 30 min
TZ = "Europe/Zurich"


def session_projects():
    """{session_id: project folder name}, from the transcript file names only."""
    d_out = {}
    for p in Path("/Users/jeanlescut/.claude/projects").glob("*/*.jsonl"):
        d_out[p.stem] = p.parent.name.replace("-Users-jeanlescut-dev-", "").replace("-Users-jeanlescut", "~")
    return d_out


def session_kinds(df_req):
    """{session_id: 'interactive' | 'script'}: interactive = it has a request from the REPL's main thread."""
    s_inter = set(df_req.loc[df_req["query_source"] == "repl_main_thread", "session_id"])
    return {sid: ("interactive" if sid in s_inter else "script") for sid in df_req["session_id"].dropna().unique()}


def jean_prompts(df_req):
    """Times Jean typed (proxy): the first request of each new prompt id in an interactive main thread."""
    df = df_req[(df_req["query_source"] == "repl_main_thread") & df_req["prompt_id"].notna()]
    return df.groupby("prompt_id")["ts"].min().sort_values().to_numpy()


def find(df_read, df_req):
    """-> DataFrame, one row per lockout (and per window that reached NEAR)."""
    d_proj, d_kind, a_prompt = session_projects(), session_kinds(df_req), jean_prompts(df_req)
    df_ok = df_req[df_req["status"] == "ok"]
    df_429 = df_req[df_req["status"] == "429"]
    l_rows = []
    for meter in ("window", "week"):
        df_m = df_read[(df_read["meter"] == meter) & df_read["resets_ts"].notna()]
        for key, df_k in df_m.groupby("resets_ts"):
            if df_k["pct"].max() < NEAR:
                continue
            start = int(df_k.loc[df_k["pct"] >= NEAR, "ts"].min())
            hit = df_k.loc[df_k["pct"] >= THRESH, "ts"]
            # the end is the reset, or an earlier confirmed drop (the week's early reset of 2026-11-13)
            df_after = df_read[(df_read["meter"] == meter) & (df_read["ts"] > start) & (df_read["resets_ts"] == key)
                               & (df_read["pct"] < NEAR - 10)]
            end = int(min(key, df_after["ts"].min())) if len(df_after) else int(key)
            lock_start = int(hit.min()) if len(hit) else None
            # who burned in the hour before (Mac telemetry only)
            t0 = lock_start or start
            df_h = df_ok[(df_ok["ts"] > t0 - 3600) & (df_ok["ts"] <= t0)]
            s_usd = df_h.groupby("session_id")["usd"].sum().sort_values(ascending=False)
            l_top = [f"{d_proj.get(sid, '?')} ({d_kind.get(sid, '?')}, ${usd:.0f})" for sid, usd in s_usd.head(3).items()]
            n_prompt_before = int(((a_prompt > t0 - ACTIVE_MIN * 60) & (a_prompt <= t0)).sum())
            df_429_in = df_429[(df_429["ts"] >= t0 - 60) & (df_429["ts"] <= end + 60)]
            n_prompt_during = int(((a_prompt > t0) & (a_prompt < end)).sum()) if lock_start else 0
            l_rows.append({
                "meter": meter, "reached": "100" if lock_start else "99",
                "start_ts": t0, "start_dt": pd.to_datetime(t0, unit="s", utc=True),
                "end_ts": end, "end_dt": pd.to_datetime(end, unit="s", utc=True),
                "lockout_min": round((end - lock_start) / 60) if lock_start else 0,
                "start_local": pd.to_datetime(t0, unit="s", utc=True).tz_convert(TZ).strftime("%a %H:%M"),
                "jean_prompts_30min_before": n_prompt_before,
                "jean_prompts_during": n_prompt_during,
                "n_429_during": len(df_429_in),
                "n_429_interactive": int(df_429_in["session_id"].map(d_kind).eq("interactive").sum()),
                "usd_hour_before": round(s_usd.sum(), 1),
                "top_sessions_hour_before": "; ".join(l_top),
            })
    return pd.DataFrame(l_rows).sort_values("start_ts").reset_index(drop=True)


if __name__ == "__main__":
    df_read, df_req = data.load()
    df = find(df_read, df_req)
    df.to_csv(data.OUT / "lockouts.csv", index=False)
    pd.set_option("display.width", 250, "display.max_colwidth", 120)
    print(df.drop(columns=["start_ts", "end_ts"]).to_string())
    # 429s that fall in no lockout found above: a check of the lockout finder
    df_429 = df_req[df_req["status"] == "429"]
    a_in = pd.Series(False, index=df_429.index)
    for r in df.itertuples():
        a_in |= (df_429["ts"] >= r.start_ts - 300) & (df_429["ts"] <= r.end_ts + 60)
    print(f"\n429s: {len(df_429)} total, {int(a_in.sum())} inside a lockout above, outside:")
    print(df_429.loc[~a_in, ["dt", "session_id", "query_source"]].assign(
        hour=lambda x: x["dt"].dt.floor("h")).groupby("hour").size().to_string())
