"""Player page (FAN VIEW and COACH VIEW, docs/product.md section 3): one player of the chosen match. Fan mode: card,
5 scores (F3), badges, top speed from detected positions (F5), heatmap, shots and passes on the pitch, the same player in
other matches (F8). Coach mode adds the raw values and rates, the thresholds, fatigue (C6), the 5-minute intensity and
the player's events (E1)."""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import cards
import clock
import pitch
import sitemap
import viz
from data import CAVEAT, clock_bounds, current_match, library, require_gold, table

SCORES = [("score_work_rate", "Work rate", "ground covered per minute"),
          ("score_sprints", "Sprints", "sprint efforts per minute"),
          ("score_passing", "Passing", "successful passes per minute"),
          ("score_progression", "Progression", "successful passes that gain 10 m or more, per minute"),
          ("score_defending", "Defending", "pressures, tackles and fouls per minute")]

sitemap.header("player")
teams = require_gold()
match = current_match(teams)
coach = st.session_state.get("view") == "coach"
colors = viz.team_colors(teams, match)
card = table("gold_player_card")
squad = card[card.match_id == match].sort_values(["team_id", "shirt_number"], ascending=[False, True])
short = {r.team_id: r.team_short for r in teams[teams.match_id == match].itertuples()}
name = short
bounds = clock_bounds(match)

chosen = st.session_state.get("player", {}).get(match)
if chosen not in set(squad.player_id):
    chosen = card[card.match_id == match].sort_values("dpm", ascending=False).player_id.iloc[0]
team_now = squad.set_index("player_id").team_id[chosen]
left, right = st.columns([1, 2])
side = left.segmented_control("Team", ["HOME", "AWAY"], default=team_now, format_func=short.get) or team_now
options = squad[squad.team_id == side]
if side != team_now:
    chosen = options.sort_values("dpm", ascending=False).player_id.iloc[0]
label = {r.player_id: f"#{r.shirt_number} {r.short_name} ({r.position})" for r in options.itertuples()}
pid = right.selectbox("Player", list(label), index=list(label).index(chosen), format_func=label.get)
st.session_state["player"] = {**st.session_state.get("player", {}), match: pid}
p = squad.set_index("player_id").loc[pid]
color = colors[p.team_id]

# ---------------------------------------------------------------- card
chips = []
if p.goals:
    chips.append(cards.badge(f"{p.goals} goal" + ("s" if p.goals > 1 else ""), "gold"))
if p.is_hub:
    chips.append(cards.badge("Hub of the team (F6)", "gold"))
if pd.notna(p.top_speed_kmh):
    chips.append(cards.badge(f"Top speed about {p.top_speed_kmh:.0f} km/h", "info"))
if not p.is_outfield:
    chips.append(cards.badge("Goalkeeper: no scores", "muted"))
elif not p.is_eligible:
    chips.append(cards.badge("Not ranked: under 20 tracked minutes", "muted"))
st.markdown(f"<div class='ml-player'>{cards.shirt(color, p.shirt_number, 84)}<div>"
            f"<div class='name' style='font-size:1.6rem'>{p['name']}</div>"
            f"<div class='ml-meta'>{p.position} · {name[p.team_id]} against {p.opponent_name} · "
            f"{p.tracked_minutes:.0f} tracked minutes</div><div>{''.join(chips)}</div></div></div>",
            unsafe_allow_html=True)

scores_col, pitch_col = st.columns([2, 3])
with scores_col:
    st.markdown("**Scores in this match** (F3)")
    rows = []
    for col, title, what in SCORES:
        value = p[col]
        ranked = pd.notna(value)
        rows.append(f"<div class='ml-score-row{'' if ranked else ' off'}' title='{what}'><div>{title}</div>"
                    f"<div class='track'><div class='fill' style='width:{value if ranked else 0}%'></div></div>"
                    f"<div class='val'>{int(value) if ranked else '–'}</div></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)
    if p.is_eligible:
        best = max(SCORES, key=lambda s: p[s[0]])
        st.caption(f"{best[1]} {int(p[best[0]])}: better than {int(p[best[0]])} % of the ranked players of this match "
                   f"on {best[2]}. Ranked: outfield players with at least 20 tracked minutes, both teams.")
    else:
        st.caption("Scores rank outfield players with at least 20 tracked minutes inside one match; this player is shown "
                   "without them.")
    k = st.columns(3)
    k[0].metric("m / min", f"{p.dpm:.0f}" if pd.notna(p.dpm) else "n/a",
                help="Per minute of tracked play (mostly ball in play)")
    k[1].metric("Sprints", f"{p.sprint_count}")
    k[2].metric("Passes", f"{p.passes_successful}", help="Successful passes")

with pitch_col:
    layers = st.pills("On the pitch", ["Heatmap", "Shots", "Passes"], default=["Heatmap"], selection_mode="multi")
    zones = table("gold_zone_occupancy")
    zones = zones[(zones.match_id == match) & (zones.player_id == pid)]
    cells = [0.0] * 24
    for z in zones.itertuples():
        cells[z.zone_id] = z.share_of_tracked_seconds
    shots = table("gold_shots")
    shots = shots[(shots.match_id == match) & (shots.player_id == pid)]
    events = table("gold_events")
    passes = events[(events.match_id == match) & (events.player_id == pid) & (events.type == "pass")]
    pitch.show(key="player_pitch", players={}, colors=colors, clickable=False, arrows={"home": "right"},
               heat={"nx": 6, "ny": 4, "cells": cells, "color": color} if "Heatmap" in layers else None,
               shots=[[r.x_start, r.y_start, r.x_end, r.y_end, bool(r.is_goal)] for r in shots.itertuples()]
               if "Shots" in layers else None,
               passes=[[r.x_start, r.y_start, r.x_end, r.y_end, r.outcome == "successful"] for r in passes.itertuples()]
               if "Passes" in layers else None)
    st.caption(f"HOME attacks to the right, AWAY to the left, in both halves. {len(shots)} shot"
               f"{'' if len(shots) == 1 else 's'}, {len(passes)} passes (faded = not successful), heatmap = share of "
               "tracked time per cell.")

# ---------------------------------------------------------------- F8: the same player in other matches
others = card[(card.source_player_id == p.source_player_id) & (card.match_id != match)]
st.markdown("**In other matches** (F8)")
if others.empty:
    st.caption("This player appears in one stored match only.")
else:
    lib = library()
    dates = {} if lib is None else dict(zip(lib.match_id, lib.match_date, strict=True))
    view = pd.concat([squad[squad.player_id == pid], others]).assign(
        match=lambda d: d.match_id.map(lambda m: f"{dates[m]:%d %b %Y}" if m in dates else m) + " v " + d.opponent_name)
    st.dataframe(view.set_index("match")[[c for c, _, _ in SCORES] + ["tracked_minutes", "top_speed_kmh"]]
                 .rename(columns={**{c: t for c, t, _ in SCORES}, "tracked_minutes": "Tracked min",
                                  "top_speed_kmh": "Top speed (km/h)"}).T, width="stretch")
    st.caption("Each score ranks the player inside its own match, so the opponent differs from column to column.")

# ---------------------------------------------------------------- coach mode
if coach:
    st.divider()
    st.markdown("<div class='ml-kicker'>COACH MODE</div>", unsafe_allow_html=True)
    raw, fatigue_col = st.columns([3, 2])
    with raw:
        st.markdown("**Raw values and rates per tracked minute**")
        st.dataframe(pd.DataFrame({
            "value": [p.tracked_minutes, p.dpm, p.top_speed_kmh, p.sprint_count, p.passes_successful,
                      p.progressive_passes, p.progressive_passes_successful, p.defensive_actions, p.involvement],
            "per tracked minute": [None, None, None, p.sprints_per_min, p.passes_successful_per_min, None,
                                   p.progressive_passes_successful_per_min, p.defensive_actions_per_min, None]},
            index=["Tracked minutes", "Distance per tracked minute (m)", "Top speed, detected (km/h)", "Sprint efforts",
                   "Successful passes", "Progressive passes", "Successful progressive passes",
                   "Defensive actions (pressure + tackle + foul)", "Involvement in team passes"])
            .map(lambda v: "" if pd.isna(v) else f"{v:.3f}".rstrip("0").rstrip(".")), width="stretch")
        st.caption("Ranked when outfield and at least 20 tracked minutes. Top speed: the best speed held over two consecutive "
                   "seconds the camera saw. Progressive pass: 10 m or more toward the opponent's goal.")
    with fatigue_col:
        st.markdown("**Fatigue** (C6)")
        fat = table("gold_player_fatigue")
        f = fat[(fat.match_id == match) & (fat.player_id == pid)].iloc[0]
        c = st.columns(3)
        c[0].metric("First 15 min", f"{f.dpm_first15:.0f}" if pd.notna(f.dpm_first15) else "n/a", help="m per minute")
        c[1].metric("Last 5 min", f"{f.dpm_last5:.0f}" if pd.notna(f.dpm_last5) else "n/a", help="m per minute")
        c[2].metric("Drop", f"{f['drop']:.0%}" if pd.notna(f["drop"]) else "n/a")
        st.caption("Shown for outfield players with 30 minutes on the pitch, 5 tracked minutes in the first window and 2 "
                   "in the last." if f.is_eligible else
                   "Greyed: below the thresholds (outfield, 30 minutes on the pitch, 5 and 2 tracked minutes).")
        win = table("gold_player_5min")
        win = win[(win.match_id == match) & (win.player_id == pid)].sort_values("window_start_ts")
        if not win.empty:
            st.bar_chart(win.assign(minutes=win.window_label + "'").set_index("minutes")["distance_m"],
                         color=color, height=180, sort=False)
            st.caption("Distance per 5-minute window (m); a window with little tracking is under-estimated.")
    st.markdown("**Events of this player** (E1)")
    mine = events[(events.match_id == match) & (events.player_id == pid)].sort_values("ts")
    kinds = sorted(mine.type.unique())
    picked = st.pills("Types", kinds, default=[k for k in kinds if k != "run"], selection_mode="multi", key="ev_types")
    shown = mine[mine.type.isin(picked or [])]
    st.dataframe(shown.assign(minute=[clock.label(r.ts, r.period, *bounds) for r in shown.itertuples()])[
                 ["minute", "type", "outcome", "third", "lane", "phase",
                                                         "xthreat", "receiver_short_name"]]
                 .assign(xthreat=lambda d: d.xthreat.map(lambda v: "" if pd.isna(v) else f"{v:.3f}"),
                         receiver_short_name=lambda d: d.receiver_short_name.fillna(""))
                 .rename(columns={"receiver_short_name": "receiver", "xthreat": "SkillCorner xThreat"}),
                 hide_index=True, width="stretch")
    st.markdown("**Ranking in the match**")
    stats = table("gold_player_match_stats")
    stats = stats[stats.match_id == match]
    metrics = {"distance_km": "Distance (km)", "sprint_count": "Sprints", "passes": "Passes",
               "passes_received": "Passes received", "pressures": "Pressures", "tackles": "Tackles", "shots": "Shots"}
    metric = st.selectbox("Metric", list(metrics), format_func=metrics.get)
    fig = viz.ranking_bars(stats.dropna(subset=[metric]), metric, colors)
    st.pyplot(fig, width="content")
    plt.close(fig)

st.caption(CAVEAT)
