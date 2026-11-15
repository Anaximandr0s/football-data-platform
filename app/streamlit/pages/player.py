"""Player page (FAN VIEW and COACH VIEW): key numbers, position heatmap, ranking inside the match (FOO-07).
The pitch component, the 5 scores and the coach mode come in step 3."""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import sitemap
import viz
from data import CAVEAT, current_match, require_gold, table

sitemap.header("player")
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

heat, ranking = st.tabs(["Heatmap", "Ranking in the match"])
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
with ranking:
    metrics = {"distance_km": "Distance (km)", "sprint_count": "Sprints", "max_speed_kmh": "Top speed (km/h)",
               "passes": "Passes", "passes_received": "Passes received", "pressures": "Pressures",
               "tackles": "Tackles", "shots": "Shots"}
    metric = st.selectbox("Metric", list(metrics), format_func=metrics.get)
    fig = viz.ranking_bars(players.dropna(subset=[metric]), metric, colors)
    st.pyplot(fig, width="content")
    plt.close(fig)
sitemap.still_to_come("player")
st.caption(CAVEAT)
