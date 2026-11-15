"""Players: key numbers, position heatmap, intensity per 5 minutes, ranking inside the match (FOO-07)."""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import viz
from data import CAVEAT, require_gold, sidebar_match, table

st.set_page_config(page_title="Players", page_icon="🏃", layout="wide")
teams = require_gold()
match = sidebar_match(teams)
colors = viz.team_colors(teams, match)
players = table("gold_player_match_stats")
players = players[players.match_id == match].sort_values(["team_id", "shirt_number"])

st.title("🏃 Players")
side = st.radio("Team", ["HOME", "AWAY"], horizontal=True,
                format_func=lambda t: teams[(teams.match_id == match) & (teams.team_id == t)].team_name.iloc[0])
squad = players[players.team_id == side]
if squad.empty:
    st.warning("No player for this team in Gold.")
    st.stop()
label = {r.player_id: f"#{r.shirt_number} {r.name} ({r.position})" for r in squad.itertuples()}
default = squad.sort_values("distance_m", ascending=False).player_id.iloc[0]
pid = st.selectbox("Player", list(label), index=list(label).index(default), format_func=label.get)
p = squad[squad.player_id == pid].iloc[0]

c = st.columns(6)
c[0].metric("Minutes on pitch", f"{p.minutes_on_pitch:.0f}")
c[1].metric("Distance", f"{p.distance_km:.2f} km")
c[2].metric("Sprints", f"{p.sprint_count}")
c[3].metric("Top speed", "n/a" if pd.isna(p.max_speed_kmh) else f"{p.max_speed_kmh:.1f} km/h")
c[4].metric("Passes", f"{p.passes_successful}/{p.passes}")
c[5].metric("Shots · goals", f"{p.shots + p.goals} · {p.goals}")
d = st.columns(6)
d[0].metric("Passes received", f"{p.passes_received}")
d[1].metric("Tackles", f"{p.tackles}")
d[2].metric("Pressures", f"{p.pressures}")
d[3].metric("Fouls", f"{p.fouls}")
d[4].metric("Tracked", f"{p.tracked_seconds / 60:.0f} min")
d[5].metric("Avg position x", "n/a" if pd.isna(p.avg_x) else f"{p.avg_x:.0f} m")

heat, intensity, ranking = st.tabs(["Heatmap", "Intensity (5 min)", "Ranking in the match"])
with heat:
    zones = table("gold_zone_occupancy")
    zones = zones[(zones.match_id == match) & (zones.player_id == pid)]
    if zones.empty:
        st.info("This player has no tracked second.")
    else:
        fig = viz.zone_heatmap(zones, colors[side])
        st.pyplot(fig, width="content")
        plt.close(fig)
        st.caption("Share of this player's tracked time in each cell of a 6 x 4 grid. Pitch seen with HOME attacking "
                   "to the right: an AWAY player attacks to the left.")
with intensity:
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
with ranking:
    metrics = {"distance_km": "Distance (km)", "sprint_count": "Sprints", "max_speed_kmh": "Top speed (km/h)",
               "passes": "Passes", "passes_received": "Passes received", "pressures": "Pressures",
               "tackles": "Tackles", "shots": "Shots"}
    metric = st.selectbox("Metric", list(metrics), format_func=metrics.get)
    fig = viz.ranking_bars(players.dropna(subset=[metric]), metric, colors)
    st.pyplot(fig, width="content")
    plt.close(fig)
st.caption(CAVEAT)
