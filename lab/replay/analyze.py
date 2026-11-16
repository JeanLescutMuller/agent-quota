"""The tables of doc/replay.md, from the replay's outputs.

Reads: lab/replay/out/ (lockouts.csv, summary.csv, replay_*.csv, lockouts_*.csv, ticks_*.csv.gz) and data.py's cache.
Writes: nothing; prints Markdown tables. Run: python3 lab/replay/analyze.py > lab/replay/out/analyze.log
"""
import numpy as np
import pandas as pd

import data
import replay

OUT = data.OUT
TZ = "Europe/Zurich"


def md(df):
    return df.to_markdown(index=False) if hasattr(df, "to_markdown") else df.to_string(index=False)


def main():
    df_read, df_req = data.load()
    prep = replay.prepare()
    a_tick = prep["tick"]
    n_tick = len(a_tick)

    print("## T1 lockouts\n")
    df_lk = pd.read_csv(OUT / "lockouts.csv")
    print(md(df_lk.drop(columns=["start_ts", "end_ts", "start_dt", "end_dt"])))

    print("\n## T2 who acts (v1, 10, 5), share of minutes\n")
    df_t = pd.read_csv(OUT / "ticks_v1_10_5.csv.gz")
    print(md(df_t["who"].value_counts().rename_axis("who").reset_index(name="minutes").assign(
        share=lambda x: (x["minutes"] / n_tick * 100).round(1))))
    print(md(pd.crosstab(df_t["window_state"], df_t["week_state"], normalize=True).mul(100).round(1).reset_index()))

    print("\n## T3 lockout ahead: how often, and how often the meter then really reached 100 %\n")
    l_rows = []
    for meter in ("window", "week"):
        seg, pct = prep["meters"][meter]["seg"], prep["meters"][meter]["pct"]
        a_peak = pd.Series(pct).groupby(seg).transform("max").to_numpy()
        a_la = (df_t[f"{meter}_state"] == "lockout ahead").to_numpy()
        l_rows.append(dict(meter=meter, rule="DESIGN §3 (as built)", minutes_flagged=int(a_la.sum()),
                           share_of_minutes=round(a_la.mean() * 100, 1),
                           lives_flagged=len(set(seg[a_la])), lives_reaching_100=len(set(seg[a_peak >= 100])),
                           minutes_flagged_in_a_life_reaching_100=int((a_la & (a_peak >= 100)).sum())))
    # the week, with two alternative burn rates (historical meter, no protector)
    seg, pct, rst = prep["meters"]["week"]["seg"], prep["meters"]["week"]["pct"], prep["meters"]["week"]["rst"]
    a_peak = pd.Series(pct).groupby(seg).transform("max").to_numpy()
    s_pct = pd.Series(pct)
    a_slope = ((s_pct - s_pct.shift(30)) / 30).where(pd.Series(seg) == pd.Series(seg).shift(30), 0).fillna(0).to_numpy()
    a_avg = pct / np.maximum(10, (a_tick - (rst - 7 * 86400)) / 60)
    a_left = (rst - a_tick) / 60
    cap = 13.2 / 300   # the week cannot climb faster than one full window (13.2 % of the week) per 5 h
    for name, a_rate in [("capped at one window per 5 h (0.044 %/min)", np.minimum(np.maximum(a_slope, a_avg) * 1.5, cap)),
                         ("average since the week opened × 1.5", a_avg * 1.5)]:
        with np.errstate(divide="ignore", invalid="ignore"):
            a_la = (a_rate > 0) & ((100 - pct) / a_rate < a_left) & ~np.isnan(rst)
        l_rows.append(dict(meter="week", rule=name, minutes_flagged=int(a_la.sum()), share_of_minutes=round(a_la.mean() * 100, 1),
                           lives_flagged=len(set(seg[a_la])), lives_reaching_100=len(set(seg[a_peak >= 100])),
                           minutes_flagged_in_a_life_reaching_100=int((a_la & (a_peak >= 100)).sum())))
        # when it first flagged the real week lockout (2026-10-25 14:22 UTC)
        i_lock = np.searchsorted(a_tick, 1792938126)
        a_hit = np.where(a_la & (seg == seg[i_lock]))[0]
        print(f"- {name}: first flag of the week that locked out: "
              f"{pd.to_datetime(a_tick[a_hit[0]], unit='s') if len(a_hit) else 'never'}")
    print(md(pd.DataFrame(l_rows)))

    print("\n## T4 the grid\n")
    df_s = pd.read_csv(OUT / "summary.csv")
    print(md(df_s.drop(columns=["by_cause", "lockouts", "lockout_min_hist"])))

    print("\n## T5 freeze events (burn, 10, 5)\n")
    for r in (3, 5, 10):
        df_f = pd.read_csv(OUT / f"replay_burn_10_{r}.csv")
        df_f["local"] = pd.to_datetime(df_f["freeze_ts"], unit="s", utc=True).dt.tz_convert(TZ).dt.strftime("%a %d %b %H:%M")
        df_f["hours"] = (df_f["release_ts"] - df_f["freeze_ts"]) / 3600
        df_e = df_f.groupby(["cause", "seg"]).agg(first_freeze=("local", "min"), first_ts=("freeze_ts", "min"),
                                                 sessions=("session_id", "nunique"),
                                                 pct_at_first=("pct_at_freeze", "min"), late=("late", "sum"),
                                                 session_hours=("hours", "sum"), usd_held=("usd_held", "sum"),
                                                 hist_peak=("hist_peak", "max"), forecast_lockout_min=("lockout_min_forecast", "max"),
                                                 harm=("harm", "max"), cost=("cost", "max")).round(1).reset_index()
        df_e = df_e.sort_values("first_ts").drop(columns=["seg", "first_ts"])
        print(f"\nreserve {r} %:\n")
        print(md(df_e))
        print(md(pd.read_csv(OUT / f"lockouts_burn_10_{r}.csv")))

    print("\n## T6 who burns: Mac $ by session kind\n")
    df_ok = df_req[df_req["status"] == "ok"].copy()
    s_inter = prep["interactive"]
    df_ok["kind"] = np.where(df_ok["session_id"].isin(s_inter), "interactive", "script (claude -p)")
    df_ok["by"] = np.where(df_ok["query_source"].fillna("").str.startswith("agent:"), "subagents", "main thread")
    df_k = df_ok.groupby(["kind", "by"])["usd"].sum().reset_index()
    df_k["share"] = (df_k["usd"] / df_k["usd"].sum() * 100).round(1)
    print(md(df_k.round(0)))
    l_rows = []
    for x in df_lk[df_lk["reached"].astype(str) == "100"].itertuples():
        df_h = df_ok[(df_ok["ts"] > x.start_ts - 3600) & (df_ok["ts"] <= x.start_ts)]
        tot = max(df_h["usd"].sum(), 1e-9)
        l_rows.append(dict(start=x.start_local, meter=x.meter, usd_hour_before=round(df_h["usd"].sum()),
                           script_share=round(df_h.loc[df_h["kind"] != "interactive", "usd"].sum() / tot * 100, 1),
                           subagent_share=round(df_h.loc[df_h["by"] == "subagents", "usd"].sum() / tot * 100, 1)))
    print(md(pd.DataFrame(l_rows)))

    print("\n## T7 Mac $ per 1 % of a window, per week (windows that reached >= 20 %)\n")
    df_w = df_read[(df_read["meter"] == "window") & df_read["resets_ts"].notna()]
    l_rows = []
    for key, df_g in df_w.groupby("resets_ts"):
        if df_g["pct"].max() >= 20:
            usd = df_ok.loc[(df_ok["ts"] > key - 18000) & (df_ok["ts"] <= key), "usd"].sum()
            l_rows.append(dict(reset=pd.to_datetime(key, unit="s"), usd_per_pct=usd / df_g["pct"].max()))
    df_c = pd.DataFrame(l_rows)
    print(md(df_c.groupby(df_c["reset"].dt.to_period("W").astype(str))["usd_per_pct"].agg(["size", "median"]).round(2).reset_index()))
    print("all:", df_c["usd_per_pct"].describe(percentiles=[.1, .5, .9]).round(2).to_dict())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
