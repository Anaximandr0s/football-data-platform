"""Match story (FAN VIEW): the scoreboard and the team comparison of the chosen match; F1, F2, F7 and E2 come in step 4."""
import streamlit as st

import sitemap
from data import CAVEAT, CREDIT, current_match, match_label, require_gold

sitemap.header("match_story")
teams = require_gold()
match = current_match(teams)
rows = teams[teams.match_id == match].set_index("team_id")

if {"HOME", "AWAY"} - set(rows.index):
    st.warning(f"{match} does not have both teams in Gold: run `make gold` again.")
    st.stop()
home, away = rows.loc["HOME"], rows.loc["AWAY"]

left, middle, right = st.columns([5, 2, 5])
left.markdown(f"<h2 style='text-align:right;margin:0'>{home.team_name}</h2>", unsafe_allow_html=True)
middle.markdown(f"<h1 style='text-align:center;margin:0'>{home.score} - {away.score}</h1>", unsafe_allow_html=True)
right.markdown(f"<h2 style='text-align:left;margin:0'>{away.team_name}</h2>", unsafe_allow_html=True)
st.caption(f"{match_label(teams, match)}. HOME attacks toward the right of the pitch in every graphic, AWAY toward the left.")

st.subheader("Team comparison")
metrics = [("Distance (km)", "distance_km", "{:.1f}"), ("Sprints (efforts)", "sprint_count", "{:.0f}"),
           ("Top speed (km/h)", "max_speed_kmh", "{:.1f}"), ("Passes", "passes", "{:.0f}"),
           ("Pass accuracy", "pass_accuracy", "{:.0%}"), ("Shots (without goals)", "shots", "{:.0f}"),
           ("Goals", "goals", "{:.0f}"), ("Tackles", "tackles", "{:.0f}"), ("Fouls", "fouls", "{:.0f}"),
           ("Pressures", "pressures", "{:.0f}")]
for label, col, fmt in metrics:
    a, b, c = st.columns([5, 2, 5])
    a.markdown(f"<div style='text-align:right;font-size:1.6rem'>{fmt.format(home[col])}</div>", unsafe_allow_html=True)
    b.markdown(f"<div style='text-align:center;color:#8a948f'>{label}</div>", unsafe_allow_html=True)
    c.markdown(f"<div style='text-align:left;font-size:1.6rem'>{fmt.format(away[col])}</div>", unsafe_allow_html=True)

with st.expander("How to read these numbers"):
    st.markdown(CAVEAT)
    st.markdown("`Shots` excludes goals; the shot map (Team analysis) shows both.")
sitemap.still_to_come("match_story")
st.caption(CREDIT)
