"""Physical & fatigue (COACH VIEW, docs/product.md: F4 per 5 min, C6): how much each player ran in every football
window, and who faded between his first 15 and his last 5 minutes on the pitch."""
import altair as alt
import streamlit as st

import charts
import coach
import glossary
import sitemap
import viz
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
top = float(win.per_minute.max()) if win.per_minute.notna().any() else 1.0
cells = alt.Chart(win).encode(
    x=alt.X("minutes:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, orient="top")),
    y=alt.Y("player:N", sort=rows, title=None, axis=alt.Axis(labelLimit=0, labelOverlap=False)),
    tooltip=[alt.Tooltip("player:N"), alt.Tooltip("minutes:N"),
             alt.Tooltip("per_minute:Q", format=".0f", title="metres per tracked minute"),
             alt.Tooltip("coverage:Q", format=".0%", title="tracked")])
grid = cells.mark_rect(cornerRadius=2, stroke="white", strokeWidth=1).encode(
    color=alt.Color("per_minute:Q", title="metres per minute", scale=alt.Scale(scheme="greens", domain=[0, top])),
    opacity=alt.condition("datum.faded", alt.value(0.35), alt.value(1)))
values = cells.mark_text(fontSize=12).encode(
    text=alt.Text("per_minute:Q", format=".0f"),
    color=alt.condition(f"datum.per_minute > {top * 0.55}", alt.value("white"), alt.value("#111111")))
st.altair_chart(charts.finish((grid + values).properties(height=30 * max(len(rows), 1))), width="stretch")
st.markdown(f"<div class='ml-meta'>Metres per {glossary.term('tracked')} minute in each football window (45+ and 90+: "
            f"stoppage time); darker = more. Faded: the camera tracked the player less than {LOW_COVERAGE:.0%} of that "
            "window, so the value is less reliable.</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- C6 fatigue
st.subheader("Who faded")
fat = table("gold_player_fatigue")
fat = fat[(fat.match_id == match) & (fat.team_id == team)]
shown = fat[fat.is_outfield].sort_values(["is_eligible", "drop"], ascending=[False, False]).assign(
    player=lambda d: d.player_id.map(names))
st.dataframe(shown.assign(enough=shown.is_eligible.map({True: "✓", False: "–"}))
             [["player", "minutes_on_pitch", "dpm_first15", "dpm_last5", "drop", "enough"]].rename(columns={
                 "minutes_on_pitch": "minutes on the pitch", "dpm_first15": "metres per minute, first 15 min",
                 "dpm_last5": "metres per minute, last 5 min", "drop": "drop", "enough": "enough data"}),
             hide_index=True, width="stretch",
             column_config={"drop": st.column_config.NumberColumn("drop", format="percent",
                                                                  help="How much less he ran at the end: 10 % = 10 % less"),
                            "minutes on the pitch": st.column_config.NumberColumn(format="%.0f"),
                            "metres per minute, first 15 min": st.column_config.NumberColumn(format="%.0f"),
                            "metres per minute, last 5 min": st.column_config.NumberColumn(format="%.0f")})
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
    bars = alt.Chart(one).encode(x=alt.X("minutes:N", sort=list(one.minutes), title=None, axis=alt.Axis(labelAngle=0)),
                                 y=alt.Y("per_minute:Q", title="metres per minute"))
    st.altair_chart(charts.finish((bars.mark_bar(color=colors[team], cornerRadius=3)
                                   + bars.mark_text(dy=-8, fontSize=charts.FONT).encode(
                                       text=alt.Text("per_minute:Q", format=".0f"))).properties(height=260)),
                    width="stretch")
    st.caption("Metres per tracked minute in each window, so a short window (45+, 90+) compares with a full one.")
    st.dataframe(one.assign(tracked=one.coverage, distance=one.distance_m.round(0),
                            per_min=one.per_minute.round(0))[
        ["minutes", "tracked", "distance", "per_min", "sprint_seconds", "passes", "pressures"]].rename(columns={
            "tracked": "seen by the camera", "distance": "distance (m)", "per_min": "metres per minute",
            "sprint_seconds": "seconds sprinting"}),
        hide_index=True, width="stretch",
        column_config={"seen by the camera": st.column_config.NumberColumn(format="percent",
                                                                           help=glossary.help("tracked"))})
st.caption(CAVEAT)
