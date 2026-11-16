"""Replay the protector v1 (protector/DESIGN.md §3-§4) minute by minute on Jean's real Max 5x history.

Reads: lab/replay/out/readings.pkl, reading_ts.npy, requests.pkl (data.py), out/lockouts.csv (lockouts.py);
       the code that will run, unchanged: src/agent_quota/forecast.py (burn rate, projection),
       state.py (the shared check: who acts), protector.py (decide).
Writes: lab/replay/out/replay_<variant>_<k>_<r>.csv (one row per freeze), out/summary.csv (one row per run),
        out/ticks_<variant>_10_5.csv.gz (who acts, per minute, at the starting values).

Closed loop: a frozen session's requests are removed from the history while it is frozen, and its $ is taken
off both meters (1 % of a window = B / 100 = $1.94, 1 % of the week = B_week / 100 = $14.69); the next ticks
see that lower meter. Its work is not added back after the release (caveat in doc/replay.md).

Variants (who may be frozen; nothing was labelled in the history, so AGENT_QUOTA_JOB is always empty):
    v1     as designed: interactive sessions are never frozen (R32); scripts (claude -p) above
           BIG_JOB_PCT_PER_HOUR are candidates
    burn   the burn rate decides for interactive sessions too: as if Jean had labelled `big` each interactive
           session while it burned >= BIG_JOB_PCT_PER_HOUR (R40's "judged by how fast it uses quota")
    subagents  as v1, but an interactive session's subagents are a unit of their own (`<session>#agents`),
           judged by burn rate like a script: freezing it holds the subagents only, never Jean's main thread
           (the hook sees `agent_id` on a subagent's tool call)

Run: python3 lab/replay/replay.py > lab/replay/out/replay.log 2>&1
"""
import sys
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
import pandas as pd

import data

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from agent_quota import config as aq_config        # noqa: E402  (the DESIGN §2 values)
from agent_quota import forecast, protector, state  # noqa: E402
from agent_quota.reading import Meter, Reading     # noqa: E402

USD_PER_PCT = {"window": 194 / 100, "week": 1469 / 100}   # B and B_week, Max 5x, 2026-10-12 (AGENTS.md)
METER_S = {"window": aq_config.WINDOW_S, "week": aq_config.WEEK_S}
TICK_S = 60


def _reading(meter, ts, pct, resets_at):
    """A one-meter Reading for forecast.burn_rate (the other meter left unknown)."""
    if meter == "window":
        return Reading(int(ts), pct, resets_at, None, None)
    return Reading(int(ts), None, None, pct, resets_at)


def prepare():
    """Per-minute inputs shared by every run: meter arrays and requests by minute."""
    df_read, df_req = data.load()
    a_rts = np.load(data.OUT / "reading_ts.npy")
    t0 = int(df_read["ts"].min()) // TICK_S * TICK_S + TICK_S
    t1 = int(df_read["ts"].max()) // TICK_S * TICK_S
    a_tick = np.arange(t0, t1 + 1, TICK_S)
    d_m = {}
    for meter in ("window", "week"):
        df = df_read[df_read["meter"] == meter].sort_values("ts", kind="stable").reset_index(drop=True)
        # segment = one life of the meter: a new reset time, or a confirmed early reset (the week, 2026-11-13)
        a_key = df["resets_ts"].fillna(-1).to_numpy()
        a_drop = df["pct"].diff().fillna(0).to_numpy() <= -10
        a_seg = np.cumsum(np.r_[True, a_key[1:] != a_key[:-1]] | a_drop)
        i = np.searchsorted(df["ts"].to_numpy(), a_tick, side="right") - 1   # last accepted reading at each tick
        a_pct = np.where(i >= 0, df["pct"].to_numpy()[i.clip(0)], 0.0)
        a_rst = np.where(i >= 0, a_key[i.clip(0)], -1)
        a_sg = np.where(i >= 0, a_seg[i.clip(0)], 0)
        # tracker rule 8: a passed reset reads 0 % (no window open)
        a_closed = (a_rst < 0) | (a_rst <= a_tick)
        a_pct = np.where(a_closed, 0.0, a_pct)
        a_sg = np.where(a_closed, -a_tick, a_sg)          # a closed meter is its own (empty) segment
        d_m[meter] = dict(pct=a_pct, rst=np.where(a_closed, np.nan, a_rst), seg=a_sg)
    # the freshest reading's age at each tick (any reading, not only the changes)
    j = np.searchsorted(a_rts, a_tick, side="right") - 1
    a_age = a_tick - np.where(j >= 0, a_rts[j.clip(0)], 0)
    # requests by minute: the minute (t - 60, t] is ingested at tick t
    df_ok = df_req[(df_req["status"] == "ok") & df_req["session_id"].notna()]
    s_inter = set(df_ok.loc[df_ok["query_source"] == "repl_main_thread", "session_id"])
    d_by_min = defaultdict(list)
    a_agent = df_ok["query_source"].fillna("").str.startswith("agent:").to_numpy()
    for ts, sid, usd, agent in zip(df_ok["ts"].to_numpy(), df_ok["session_id"].to_numpy(), df_ok["usd"].to_numpy(), a_agent):
        d_by_min[(int(ts) + TICK_S - 1) // TICK_S * TICK_S].append((sid, float(usd), int(ts), bool(agent)))
    return dict(tick=a_tick, meters=d_m, age=a_age, by_min=d_by_min, interactive=s_inter)


def run(prep, variant="v1", lockout_vs_delay=10, reserve=5, keep_ticks=False):
    """One closed-loop replay. -> (df_freezes, d_summary, df_ticks or None)."""
    cfg = {k: getattr(aq_config, k) for k in dir(aq_config) if k.isupper()}
    cfg.update(LOCKOUT_VS_DELAY=lockout_vs_delay, RESERVE_WINDOW_PCT=reserve, RESERVE_WEEK_PCT=reserve)
    a_tick, d_m, a_age = prep["tick"], prep["meters"], prep["age"]
    s_inter = prep["interactive"]
    d_avoid = {"window": defaultdict(float), "week": defaultdict(float)}   # $ removed, per meter segment
    d_hist = {"window": deque(), "week": deque()}                          # (tick, seg, cf pct) of the last 30 min
    dq_usd = deque()                                                       # (tick, sid, usd) of the last 30 min
    d_usd30 = defaultdict(float)
    d_last = {}                                                            # sid -> last request ts (not frozen)
    previous, l_freeze, d_open = {}, [], {}                                # d_open: sid -> freeze record
    l_ticks = []
    d_cf_all = {m: np.zeros(len(a_tick)) for m in ("window", "week")}     # the replayed meters, per tick
    for k, now in enumerate(a_tick):
        now = int(now)
        frozen = {sid for sid, d in previous.items() if d.action == "freeze"}
        # 1. ingest the minute's requests: a frozen session's are removed (its $ comes off the meters)
        for sid, usd, ts, agent in prep["by_min"].get(now, ()):
            if variant == "subagents" and agent and sid in s_inter:
                sid += "#agents"     # an interactive session's subagents: their own unit, judged by burn rate
            if sid in frozen:
                d_open[sid]["usd_held"] += usd
                for meter in ("window", "week"):
                    d_avoid[meter][d_m[meter]["seg"][k]] += usd
                continue
            dq_usd.append((now, sid, usd)); d_usd30[sid] += usd
            d_last[sid] = ts
        while dq_usd and dq_usd[0][0] <= now - aq_config.RECENT_MIN * 60:
            _, sid, usd = dq_usd.popleft(); d_usd30[sid] -= usd
            if d_usd30[sid] <= 1e-9:
                del d_usd30[sid]
        # 2. the meters as the protector would have read them (counterfactual: minus the removed $)
        meters, projections, d_cf = {}, {}, {}
        for meter in ("window", "week"):
            seg, rst = d_m[meter]["seg"][k], d_m[meter]["rst"][k]
            cf = max(0.0, d_m[meter]["pct"][k] - d_avoid[meter][seg] / USD_PER_PCT[meter])
            d_cf[meter] = cf; d_cf_all[meter][k] = cf
            dq = d_hist[meter]; dq.append((now, seg, cf))
            while dq[0][0] < now - aq_config.RECENT_MIN * 60:
                dq.popleft()
            if np.isnan(rst):
                meters[meter], projections[meter] = None, forecast.Projection(None, 0.0, 0.0)
                continue
            # the repo's own forecast (forecast.burn_rate, project) fed with the replayed meter: two readings,
            # the one RECENT_MIN ago (its own reset time: a reset in between is seen as such) and now's
            ts_30, seg_30, cf_30 = dq[0]
            rst_30 = rst if seg_30 == seg else (d_m[meter]["rst"][k - (now - ts_30) // TICK_S] if seg_30 > 0 else None)
            rst_30 = None if rst_30 is None or np.isnan(rst_30) else int(rst_30)
            l_hist = [_reading(meter, ts_30, cf_30, rst_30), _reading(meter, now, cf, int(rst))]
            rate = forecast.burn_rate(l_hist, meter, now)
            meters[meter] = Meter(meter, cf, int(rst), int(now - a_age[k]), bool(a_age[k] > aq_config.READING_MAX_AGE_S))
            projections[meter] = forecast.project(meters[meter], rate, now)
        # the shared check (state.py): who acts at this tick (R1)
        stale = bool(a_age[k] > aq_config.READING_MAX_AGE_S)
        m_win = meters["window"] or Meter("window", 0.0, None, int(now - a_age[k]), stale)   # no window open: 0 %
        m_week = meters["week"] or Meter("week", 0.0, None, int(now - a_age[k]), stale)
        s_win = state.meter_state(m_win, projections["window"])
        s_week = state.meter_state(m_week, projections["week"], state.week_spare_pct(m_week, now))
        who = state.who_acts(s_win, s_week)
        # 3. the sessions the hook would know (seen in the last hour; frozen ones stay in `previous`)
        total = sum(d_usd30.values())
        w_rate = projections["window"].rate
        sessions = {}
        for sid, ts in d_last.items():
            if ts < now - 3600:
                continue
            label = ""
            if variant == "burn" and sid in s_inter and total > 0:
                if d_usd30.get(sid, 0) / total * w_rate * 60 >= cfg["BIG_JOB_PCT_PER_HOUR"]:
                    label = "big"
            sessions[sid] = {"label": label, "interactive": sid in s_inter, "last_ts": ts}
        if not sessions and not frozen:
            previous = {}
            if keep_ticks:
                l_ticks.append((now, d_cf["window"], d_cf["week"], s_win, s_week, who, stale, 0, 0))
            continue
        trace = {}
        dec = protector.decide(now, meters, projections, sessions, dict(d_usd30), {}, cfg, previous, trace)
        # 4. bookkeeping of freezes and releases
        for sid, d in dec.items():
            was = sid in frozen
            if d.action == "freeze" and not was:
                a = trace["meters"][d.cause]
                d_open[sid] = dict(session_id=sid, interactive=sid in s_inter, cause=d.cause, freeze_ts=now,
                                   pct_at_freeze=round(a["pct"], 1), reserve=reserve,
                                   late=a["pct"] >= 100 - reserve, resets_at=a["resets_at"],
                                   seg=d_m[d.cause]["seg"][k], lockout_min_forecast=round(a["lockout_min"]),
                                   harm=round(a["harm"]), cost=round(a["cost"]), usd_held=0.0)
            elif d.action != "freeze" and was:
                rec = d_open.pop(sid); rec["release_ts"] = now; l_freeze.append(rec)
        previous = dec
        if keep_ticks:
            l_ticks.append((now, d_cf["window"], d_cf["week"], s_win, s_week, who, stale,
                            sum(1 for d in dec.values() if d.action == "freeze"), len(sessions)))
    for rec in d_open.values():
        rec["release_ts"] = int(a_tick[-1]); l_freeze.append(rec)
    df_f = pd.DataFrame(l_freeze)
    df_t = pd.DataFrame(l_ticks, columns=["ts", "window_pct", "week_pct", "window_state", "week_state", "who", "stale", "n_frozen", "n_sessions"]) if keep_ticks else None
    return df_f, d_cf_all, df_t


def score(prep, df_f, d_cf_all, df_lock, variant, k, r):
    """Count what the run did against the lockouts that happened."""
    d_m, a_tick = prep["meters"], prep["tick"]
    d = dict(variant=variant, lockout_vs_delay=k, reserve_pct=r)
    # a lockout avoided = its meter's counterfactual peak stays under 100 % (under 100 - reserve: reserve kept)
    l_lk = []
    for row in df_lock[df_lock["reached"].astype(str) == "100"].itertuples():
        meter = row.meter
        i = np.searchsorted(a_tick, row.start_ts)
        seg = d_m[meter]["seg"][min(i, len(a_tick) - 1)]
        a_in = d_m[meter]["seg"] == seg
        a_hit = np.where(a_in & (d_cf_all[meter] >= 100))[0]
        lock_min = (row.end_ts - a_tick[a_hit[0]]) / 60 if len(a_hit) else 0.0
        l_lk.append(dict(meter=meter, start=row.start_dt, hist_peak=d_m[meter]["pct"][a_in].max(),
                         replay_peak=round(d_cf_all[meter][a_in].max(), 1),
                         avoided=len(a_hit) == 0, hist_lockout_min=row.lockout_min, replay_lockout_min=round(lock_min)))
    df_lk = pd.DataFrame(l_lk)
    d.update(lockouts=len(df_lk), avoided=int(df_lk["avoided"].sum()),
             reserve_kept=int((df_lk["replay_peak"] < 100 - r).sum()),
             lockout_min_hist=int(df_lk["hist_lockout_min"].sum()), lockout_min_replay=int(df_lk["replay_lockout_min"].sum()))
    if len(df_f):
        # a false alarm = a freeze whose cause meter, in the history (no protector), never reached 100 % in that segment
        a_peak = [d_m[f.cause]["pct"][d_m[f.cause]["seg"] == f.seg].max() for f in df_f.itertuples()]
        df_f["hist_peak"] = a_peak
        df_f["false_alarm"] = df_f["hist_peak"] < 100
        df_f["hours"] = (df_f["release_ts"] - df_f["freeze_ts"]) / 3600
        # an event = the freezes caused by one meter in one of its lives (one window, one week)
        df_ev = df_f.groupby(["cause", "seg"]).agg(first=("freeze_ts", "min"), fa=("false_alarm", "all"))
        d.update(events=len(df_ev), false_alarm_events=int(df_ev["fa"].sum()))
        d.update(freezes=len(df_f), sessions_frozen=df_f["session_id"].nunique(),
                 interactive_frozen=int(df_f["interactive"].sum()),
                 freeze_hours=round(df_f["hours"].sum(), 1),
                 freeze_hours_with_work=round(df_f.loc[df_f["usd_held"] > 0, "hours"].sum(), 1),
                 usd_held=round(df_f["usd_held"].sum()),
                 false_alarms=int(df_f["false_alarm"].sum()), late=int(df_f["late"].sum()),
                 by_cause=df_f["cause"].value_counts().to_dict())
    else:
        d.update(events=0, false_alarm_events=0, freezes=0, sessions_frozen=0, interactive_frozen=0, freeze_hours=0, freeze_hours_with_work=0,
                 usd_held=0, false_alarms=0, late=0, by_cause={})
    return d, df_lk


def calibrate(prep):
    """$ on this Mac per 1 % of a window, per window that moved >= 20 %: how far B = $194 holds (Mac only)."""
    df_read, df_req = data.load()
    df_ok = df_req[df_req["status"] == "ok"]
    l_rows = []
    df_w = df_read[(df_read["meter"] == "window") & df_read["resets_ts"].notna()]
    for key, df_k in df_w.groupby("resets_ts"):
        if df_k["pct"].max() < 20:
            continue
        usd = df_ok.loc[(df_ok["ts"] > key - METER_S["window"]) & (df_ok["ts"] <= key), "usd"].sum()
        l_rows.append(usd / df_k["pct"].max())
    s = pd.Series(l_rows)
    return dict(windows=len(s), median=round(s.median(), 2), p25=round(s.quantile(.25), 2), p75=round(s.quantile(.75), 2))


if __name__ == "__main__":
    prep = prepare()
    df_lock = pd.read_csv(data.OUT / "lockouts.csv")
    print("ticks:", len(prep["tick"]), "from", pd.to_datetime(prep["tick"][0], unit="s"), "to", pd.to_datetime(prep["tick"][-1], unit="s"))
    print("calibration, Mac $ per 1 % of a window:", calibrate(prep))
    l_sum = []
    for variant in ("v1", "burn", "subagents"):
        for k in (3, 10, 30):
            for r in (3, 5, 10):
                keep = (k, r) == (10, 5)
                df_f, d_cf_all, df_t = run(prep, variant, k, r, keep_ticks=keep)
                d, df_lk = score(prep, df_f, d_cf_all, df_lock, variant, k, r)
                l_sum.append(d)
                df_f.to_csv(data.OUT / f"replay_{variant}_{k}_{r}.csv", index=False)
                df_lk.to_csv(data.OUT / f"lockouts_{variant}_{k}_{r}.csv", index=False)
                if keep:
                    df_t.to_csv(data.OUT / f"ticks_{variant}_10_5.csv.gz", index=False)
                print(d, flush=True)
    pd.DataFrame(l_sum).to_csv(data.OUT / "summary.csv", index=False)
