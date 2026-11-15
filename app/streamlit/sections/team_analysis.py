"""Team analysis (COACH VIEW): shot map of both teams and pass network of one team (FOO-07); shape, pressing,
build-up and attack side come in step 5."""
import matplotlib.pyplot as plt
import streamlit as st

import clock
import sitemap
import viz
from data import CAVEAT, clock_bounds, current_match, require_gold, table

sitemap.header("team_analysis")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
name = {r.team_id: r.team_short for r in teams[teams.match_id == match].itertuples()}

shots_tab, network_tab = st.tabs(["Shot map", "Pass network"])

with shots_tab:
    shots = table("gold_shots")
    shots = shots[shots.match_id == match].sort_values("ts")
    chosen = st.multiselect("Teams", ["HOME", "AWAY"], default=["HOME", "AWAY"], format_func=name.get)
    goals_only = st.checkbox("Goals only", value=False)
    view = shots[shots.team_id.isin(chosen)]
    if goals_only:
        view = view[view.is_goal]
    if view.empty:
        st.info("No shot to show with these filters.")
    else:
        fig = viz.shot_map(view, colors)
        st.pyplot(fig, width="content")
        plt.close(fig)
        st.caption("Star = goal, circle = other shot. Arrow = direction of attack. HOME shoots at the right goal, AWAY "
                   "at the left goal. The line goes from the shot to where the action ended.")
        bounds = clock_bounds(match)
        table_view = view.assign(time=[clock.label(r.ts, r.period, *bounds) for r in view.itertuples()],
                                 team=view.team_id.map(name),
                                 distance_m=view.distance_to_goal_m.round(1),
                                 score=view.score_home_after.astype(str) + "-" + view.score_away_after.astype(str))
        st.dataframe(table_view[["time", "team", "player_name", "type", "distance_m", "score"]]
                     .rename(columns={"distance_m": "distance to goal (m)", "score": "score after"}),
                     hide_index=True, width="stretch")

with network_tab:
    side = st.radio("Team", ["HOME", "AWAY"], horizontal=True, format_func=name.get, key="net_team")
    net = table("gold_pass_network")
    net = net[(net.match_id == match) & (net.team_id == side)]
    players = table("gold_player_match_stats")
    players = players[(players.match_id == match) & (players.team_id == side)]
    if net.empty:
        st.info("No pass with a known receiver for this team.")
    else:
        top = int(net.passes.max())
        minimum = st.slider("Minimum passes between two players", 1, max(top, 2), min(3, top))
        fig = viz.pass_network(net, players, colors[side], minimum)
        st.pyplot(fig, width="content")
        plt.close(fig)
        st.caption("Node = player at his average position (number = shirt, size = passes made). Line width = passes "
                   "between the two players.")
        pairs = net.sort_values("passes", ascending=False).head(10)
        st.markdown("**Most frequent connections**")
        st.dataframe(pairs[["passer_name", "receiver_name", "passes", "passes_successful"]], hide_index=True,
                     width="stretch")
sitemap.still_to_come("team_analysis")
st.caption(CAVEAT)
