"""Physical & fatigue (COACH VIEW): distance and sprints per 5-minute window of one player (F4 per 5 min). Fatigue
(C6) comes in step 5."""
import streamlit as st

import sitemap
import viz
from data import CAVEAT, current_match, require_gold, table

sitemap.header("physical_fatigue")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
players = table("gold_player_match_stats")
players = players[players.match_id == match].sort_values(["team_id", "shirt_number"])

side = st.radio("Team", ["HOME", "AWAY"], horizontal=True,
                format_func=lambda t: teams[(teams.match_id == match) & (teams.team_id == t)].team_name.iloc[0])
squad = players[players.team_id == side]
if squad.empty:
    st.warning("No player for this team in Gold.")
    st.stop()
label = {r.player_id: f"#{r.shirt_number} {r.name} ({r.position})" for r in squad.itertuples()}
default = squad.sort_values("distance_m", ascending=False).player_id.iloc[0]
pid = st.selectbox("Player", list(label), index=list(label).index(default), format_func=label.get)

win = table("gold_player_5min")
win = win[(win.match_id == match) & (win.player_id == pid)].sort_values("window_start_ts")
if win.empty:
    st.info("No window for this player.")
else:
    win = win.assign(minute=(win.window_start_ts // 60).astype(str) + "-" + (win.window_end_ts // 60).astype(str))
    st.markdown("**Distance per 5-minute window (m)**")
    st.bar_chart(win.set_index("minute")["distance_m"], color=colors[side])
    st.markdown("**Sprint seconds per window**")
    st.bar_chart(win.set_index("minute")["sprint_seconds"], color=colors[side])
    st.caption("A window with low coverage (below) is incomplete: its distance is under-estimated.")
    st.dataframe(win[["minute", "coverage", "distance_m", "sprint_seconds", "max_speed_kmh", "passes", "pressures"]],
                 hide_index=True, width="stretch")
sitemap.still_to_come("physical_fatigue")
st.caption(CAVEAT)
