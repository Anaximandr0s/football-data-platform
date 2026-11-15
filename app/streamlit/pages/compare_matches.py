"""Compare matches: team-level comparison of the matches in Gold (FOO-09). Player ids are local to a match, so no
player-level comparison is offered."""
import pandas as pd
import streamlit as st

from data import CAVEAT, match_label, require_gold, sidebar_match

st.set_page_config(page_title="Compare matches", page_icon="⚖️", layout="wide")
teams = require_gold()
sidebar_match(teams)   # keeps the match picker of the other pages in the sidebar

st.title("⚖️ Compare matches")
ids = sorted(teams.match_id.unique())
if len(ids) < 2:
    st.info("Only one match is in Gold: run `make silver MATCH=\"m001 m002\"` and `make gold` to compare two.")
    st.stop()
chosen = st.multiselect("Matches", ids, default=ids[:2], format_func=lambda m: match_label(teams, m))
if len(chosen) < 2:
    st.info("Pick at least two matches.")
    st.stop()

view = teams[teams.match_id.isin(chosen)].copy()
view["who"] = view.match_id + " · " + view.team_short
metrics = {"distance_km": "Distance (km)", "sprint_count": "Sprints", "max_speed_kmh": "Top speed (km/h)",
           "passes": "Passes", "pass_accuracy": "Pass accuracy", "shots": "Shots", "goals": "Goals",
           "tackles": "Tackles", "fouls": "Fouls", "pressures": "Pressures", "avg_x": "Average position x (m)"}
metric = st.selectbox("Metric", list(metrics), format_func=metrics.get)
st.bar_chart(view.set_index("who")[metric], horizontal=True)

st.subheader("All metrics")
table = view.set_index("who")[list(metrics)].rename(columns=metrics).T
st.dataframe(table.map(lambda v: "" if pd.isna(v) else f"{v:.2f}".rstrip("0").rstrip(".")), width="stretch")
st.caption("Possession is not in the source. " + CAVEAT)
