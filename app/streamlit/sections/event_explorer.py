"""Event explorer (COACH VIEW, docs/product.md: E1, E2): every action and run of the match, filtered by team, type,
player, phase, period and football minutes; shown as arrows or as a heatmap of start points, with a summary, a
head-to-head of two players on the same filters, and the momentum of the match."""
import numpy as np
import pandas as pd
import streamlit as st

import charts
import clock
import coach
import pitch
import sitemap
import viz
from data import CAVEAT, clock_bounds, current_match, require_gold, table

MAX_ARROWS = 400
GRID = (12, 8)   # heatmap cells: 8.75 m x 8.5 m


def say(sentence) -> None:
    st.markdown(f"<p class='ml-say'>{sentence.text}</p>", unsafe_allow_html=True)


def summary(ev: pd.DataFrame) -> pd.DataFrame:
    """Per type: count, success (passes: successful; runs: received), mean SkillCorner xThreat."""
    out = ev.groupby("type").agg(count=("event_id", "size"), xthreat=("xthreat", "mean"))
    out["success"] = np.nan
    passes, runs = ev[ev.type == "pass"], ev[ev.type == "run"]
    if len(passes):
        out.loc["pass", "success"] = (passes.outcome == "successful").mean()
    if len(runs):
        out.loc["run", "success"] = runs.received.astype(float).mean()
    return out.sort_values("count", ascending=False)


def as_text(df: pd.DataFrame, formats: dict) -> pd.DataFrame:
    """Numbers as text for the table, "-" where there is no value (a shot has no success rate)."""
    return df.apply(lambda col: col.map(lambda v: "-" if pd.isna(v) else formats.get(col.name, "{}").format(v)))


def heat_cells(ev: pd.DataFrame) -> list[float]:
    nx, ny = GRID
    zx = np.minimum((ev.x_start / 105 * nx).astype(int), nx - 1)
    zy = np.minimum((ev.y_start / 68 * ny).astype(int), ny - 1)
    counts = np.bincount((zy * nx + zx).to_numpy(), minlength=nx * ny)
    return (counts / max(counts.sum(), 1)).tolist()


sitemap.header("event_explorer")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
short = {r.team_id: r.team_short for r in teams[teams.match_id == match].itertuples()}
bounds = clock_bounds(match)
events = table("gold_events")
events = events[(events.match_id == match) & events.x_start.notna()].copy()
events["window"] = [clock.window_index(r.ts, r.period, *bounds) for r in events.itertuples()]
events["minute"] = [clock.label(r.ts, r.period, *bounds) for r in events.itertuples()]
timeline = table("gold_match_timeline")
timeline = timeline[timeline.match_id == match]
labels = timeline.drop_duplicates("window_index").sort_values("window_index")
window_names = [f"{w}'" for w in labels.window_label]
window_ids = dict(zip(window_names, labels.window_index, strict=True))

# ---------------------------------------------------------------- filters
f1, f2, f3 = st.columns([1, 2, 2])
side = f1.segmented_control("Team", ["Both", "HOME", "AWAY"], default="HOME",
                            format_func=lambda t: short.get(t, t), key="ee_team") or "Both"
kinds = sorted(events.type.unique())
chosen_kinds = f2.multiselect("Types (runs included)", kinds, default=[k for k in ("pass", "shot", "goal") if k in kinds])
pool = events if side == "Both" else events[events.team_id == side]
who = dict(zip(pool.player_id, pool.player_short_name, strict=False))
chosen_players = f3.multiselect("Players (all if empty)", sorted(who, key=who.get), format_func=who.get)
g1, g2, g3 = st.columns([2, 1, 3])
phases = sorted(events.phase.dropna().unique())
chosen_phases = g1.multiselect("Phase of play (all if empty)", phases)
period = g2.segmented_control("Half", ["Both", 1, 2], default="Both", key="ee_period") or "Both"
first, last = g3.select_slider("Minutes", options=window_names, value=(window_names[0], window_names[-1]))

ev = pool[pool.type.isin(chosen_kinds) & pool.window.between(window_ids[first], window_ids[last])]
if chosen_players:
    ev = ev[ev.player_id.isin(chosen_players)]
if chosen_phases:
    ev = ev[ev.phase.isin(chosen_phases)]
if period != "Both":
    ev = ev[ev.period == period]

# ---------------------------------------------------------------- what the filters kept (E1)
view_col, table_col = st.columns([3, 2])
with view_col:
    view = st.segmented_control("Show", ["Arrows", "Heatmap"], default="Arrows", key="ee_view") or "Arrows"
    color = colors[side] if side in colors else "#e8f0ea"
    if view == "Arrows":
        shown = ev.head(MAX_ARROWS)
        ok = [(r.outcome == "successful") if r.type == "pass" else bool(r.received) if r.type == "run" else True
              for r in shown.itertuples()]
        pitch.show(key="ee_pitch", players={}, colors=colors, clickable=False, arrows={"home": "right"},
                   passes=[[r.x_start, r.y_start, r.x_end, r.y_end, k] for r, k in zip(shown.itertuples(), ok,
                                                                                         strict=True)])
        cut = f" (the first {MAX_ARROWS} shown)" if len(ev) > MAX_ARROWS else ""
        st.caption(f"From start to end of each event{cut}. Faded: pass not successful, run not received. "
                   f"{short['HOME']} attacks to the right, {short['AWAY']} to the left.")
    else:
        pitch.show(key="ee_heat", players={}, colors=colors, clickable=False, arrows={"home": "right"},
                   heat={"nx": GRID[0], "ny": GRID[1], "cells": heat_cells(ev), "color": color})
        st.caption("Where the filtered events started: share of them per cell of 8.75 m x 8.5 m.")
    say(coach.events_summary(ev))
with table_col:
    st.markdown("**Summary**")
    st.dataframe(as_text(summary(ev), {"count": "{:.0f}", "success": "{:.0%}", "xthreat": "{:.3f}"})
                 .rename(columns={"xthreat": "SkillCorner xThreat (mean)"}), width="stretch")
    st.caption("Success: successful passes, received runs. xThreat values the option a pass or run aimed at; it is not xG.")
    st.markdown("**Head-to-head** on the same filters")
    everyone = dict(zip(events.player_id, events.player_short_name, strict=False))
    ids = sorted(everyone, key=everyone.get)
    h1, h2 = st.columns(2)
    a = h1.selectbox("Player A", ids, format_func=everyone.get, key="ee_a")
    b = h2.selectbox("Player B", ids, index=min(1, len(ids) - 1), format_func=everyone.get, key="ee_b")
    base = events[events.type.isin(chosen_kinds) & events.window.between(window_ids[first], window_ids[last])]
    if chosen_phases:
        base = base[base.phase.isin(chosen_phases)]
    if period != "Both":
        base = base[base.period == period]
    duel = {}
    for pid in dict.fromkeys((a, b)):
        mine = base[base.player_id == pid]
        passes = mine[mine.type == "pass"]
        duel[everyone[pid]] = {"events": len(mine), "passes": len(passes),
                               "pass success": (passes.outcome == "successful").mean() if len(passes) else np.nan,
                               "in the final third": int((mine.third == "final").sum()),
                               "mean xThreat": mine.xthreat.mean()}
    st.dataframe(as_text(pd.DataFrame(duel).T, {"events": "{:.0f}", "passes": "{:.0f}", "pass success": "{:.0%}",
                                              "in the final third": "{:.0f}", "mean xThreat": "{:.3f}"}).T,
                 width="stretch")
with st.expander(f"The {len(ev)} events"):
    st.dataframe(ev[["minute", "type", "player_short_name", "outcome", "third", "lane", "phase", "xthreat"]]
                 .rename(columns={"player_short_name": "player", "xthreat": "SkillCorner xThreat"}),
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------- momentum (E2)
st.subheader("Momentum")
goal_rows = events[events.type == "goal"]
goals = pd.DataFrame({"minute": goal_rows.ts / 60, "team": goal_rows.team_id, "team_name": goal_rows.team_id.map(short),
                      "label": goal_rows.minute + " " + goal_rows.player_short_name})
end = int(timeline.window_end_ts.max())
st.altair_chart(charts.momentum(timeline, goals, colors, short, end / 60, clock.axis_ticks(*bounds, end_ts=end),
                                bounds[1] / 60 if bounds[1] is not None else None), width="stretch")
st.caption("SkillCorner xThreat of the successful passes per 5 minutes, HOME minus AWAY; above the line "
           f"{short['HOME']} was on top. Not xG.")
st.caption(CAVEAT)
