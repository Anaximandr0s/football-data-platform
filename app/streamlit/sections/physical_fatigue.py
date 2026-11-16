"""Physical & fatigue (COACH VIEW, docs/product.md: F4 per 5 min, C6): how much each player ran in every football
window, and who faded between his first 15 and his last 5 minutes on the pitch."""
import altair as alt
import streamlit as st

import coach
import sitemap
import viz
from charts import TEXT
from data import CAVEAT, current_match, require_gold, table

LOW_COVERAGE = 0.5   # a window tracked less than half of its length is faded: its distance is under-estimated


def say(sentence) -> None:
    if sentence:
        st.markdown(f"<p class='ml-say'>{sentence.text}</p>", unsafe_allow_html=True)


sitemap.header("physical_fatigue")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
short = {r.team_id: r.team_short for r in teams[teams.match_id == match].itertuples()}
team = st.segmented_control("Team", ["HOME", "AWAY"], default="HOME", format_func=short.get, key="pf_team") or "HOME"

players = table("gold_player_match_stats")
players = players[(players.match_id == match) & (players.team_id == team)]
names = dict(zip(players.player_id, "#" + players.shirt_number.astype(str) + " " + players.short_name, strict=True))
win = table("gold_player_5min")
win = win[(win.match_id == match) & (win.team_id == team)].copy()
win["player"] = win.player_id.map(names)
win["minutes"] = win.window_label + "'"
win["per_minute"] = (win.distance_m / (win.tracked_seconds / 60)).where(win.tracked_seconds > 0)
win["faded"] = win.coverage < LOW_COVERAGE

# ---------------------------------------------------------------- F4 per 5 minutes, the whole team
st.subheader("Distance per minute, every 5 minutes")
order = list(win.sort_values("window_index").minutes.unique())
rows = list(players.sort_values("distance_m", ascending=False).player_id.map(names))
grid = alt.Chart(win).mark_rect(cornerRadius=2).encode(
    x=alt.X("minutes:N", sort=order, title=None, axis=alt.Axis(labelColor=TEXT, labelAngle=0)),
    y=alt.Y("player:N", sort=rows, title=None, axis=alt.Axis(labelColor=TEXT)),
    color=alt.Color("per_minute:Q", title="m / min", scale=alt.Scale(range=["#12221a", colors[team]])),
    opacity=alt.condition("datum.faded", alt.value(0.35), alt.value(1)),
    tooltip=[alt.Tooltip("player:N"), alt.Tooltip("minutes:N"), alt.Tooltip("per_minute:Q", format=".0f",
                                                                            title="m per tracked minute"),
             alt.Tooltip("coverage:Q", format=".0%", title="tracked")]).properties(height=22 * max(len(rows), 1))
st.altair_chart(grid, width="stretch")
st.caption("Metres per tracked minute in each football window (45+ and 90+: stoppage time). Faded: the camera tracked "
           f"the player less than {LOW_COVERAGE:.0%} of that window, so the value is less reliable.")

# ---------------------------------------------------------------- C6 fatigue
st.subheader("Who faded")
fat = table("gold_player_fatigue")
fat = fat[(fat.match_id == match) & (fat.team_id == team)]
shown = fat[fat.is_outfield].sort_values(["is_eligible", "drop"], ascending=[False, False]).assign(
    player=lambda d: d.player_id.map(names))
st.dataframe(shown[["player", "minutes_on_pitch", "dpm_first15", "dpm_last5", "drop", "is_eligible"]].rename(columns={
    "minutes_on_pitch": "minutes on the pitch", "dpm_first15": "m/min, first 15", "dpm_last5": "m/min, last 5",
    "is_eligible": "enough data"}),
    hide_index=True, width="stretch",
    column_config={"drop": st.column_config.NumberColumn("drop", format="percent"),
                   "minutes on the pitch": st.column_config.NumberColumn(format="%.0f")})
st.caption("Distance per minute in the player's first 15 minutes on the pitch against his last 5. Enough data: outfield, "
           "30 minutes on the pitch, 5 tracked minutes in the first window and 2 in the last; the others are listed "
           "below for information. The last minutes also hold stoppages and changes of the score: a signal, not a "
           "diagnosis.")
say(coach.fatigue(fat.assign(short_name=fat.player_id.map(players.set_index("player_id").short_name)), team, short))

# ---------------------------------------------------------------- one player
st.subheader("One player, window by window")
default = players.sort_values("distance_m", ascending=False).player_id.iloc[0]
pid = st.selectbox("Player", list(names), index=list(names).index(default), format_func=names.get)
one = win[win.player_id == pid].sort_values("window_index")
if one.empty:
    st.info("No window for this player.")
else:
    st.bar_chart(one.set_index("minutes")["distance_m"], color=colors[team], sort=False)
    st.caption("Distance in each window (m). A short window (45+, 90+) or one with little tracking is under-estimated.")
    st.dataframe(one[["minutes", "coverage", "distance_m", "sprint_seconds", "max_speed_kmh", "passes", "pressures"]],
                 hide_index=True, width="stretch",
                 column_config={"max_speed_kmh": st.column_config.NumberColumn(
                     "fastest second (raw)", help="One second, estimated positions included: not the top speed (F5)")})
st.caption(CAVEAT)
