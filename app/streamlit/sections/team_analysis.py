"""Team analysis (COACH VIEW, docs/product.md: C1-C5, S1, F6): how one team organises with and without the ball,
presses, builds up and attacks, with the shot map and the pass network. One sentence under each part, built by
coach.py from the Gold numbers shown."""
import altair as alt
import pandas as pd
import streamlit as st

import clock
import coach
import sitemap
import views
import viz
from charts import TEXT
from data import CAVEAT, clock_bounds, current_match, require_gold, table

PHASES = {"in_possession": "With the ball", "out_of_possession": "Without the ball", "unknown": "Ball dead or contested"}


def say(sentence) -> None:
    if sentence:
        st.markdown(f"<p class='ml-say'>{sentence.text}</p>", unsafe_allow_html=True)


sitemap.header("team_analysis")
teams = require_gold()
match = current_match(teams)
colors = viz.team_colors(teams, match)
short = {r.team_id: r.team_short for r in teams[teams.match_id == match].itertuples()}
team = st.segmented_control("Team", ["HOME", "AWAY"], default="HOME", format_func=short.get, key="ta_team") or "HOME"
other = "AWAY" if team == "HOME" else "HOME"


def mine(name: str) -> pd.DataFrame:
    t = table(name)
    return t[t.match_id == match]


profile, shape_rows, press, build, space = (mine(t) for t in ("gold_team_profile", "gold_team_shape", "gold_pressing",
                                                              "gold_team_build_up", "gold_space_control"))

# ---------------------------------------------------------------- shape (C1, C2)
st.subheader("Shape")
s = shape_rows[shape_rows.team_id == team].set_index("phase")
cols = st.columns(3)
for col, (phase, title) in zip(cols, PHASES.items(), strict=True):
    if phase not in s.index:
        continue
    r = s.loc[phase]
    col.markdown(f"<div class='ml-card'><div class='ml-kicker'>{title.upper()}</div>"
                 f"<div class='ml-stats'><div><span>Width</span><b>{r.width:.0f} m</b></div>"
                 f"<div><span>Outfield block length</span><b>{r.length:.0f} m</b></div>"
                 f"<div><span>Defensive line from own goal</span><b>{r.defensive_line_height:.0f} m</b></div>"
                 f"<div><span>Seconds used</span><b>{int(r.seconds_used)}</b></div></div>"
                 f"<div class='ml-meta'>{r.detected_share:.0%} of the positions seen by the camera</div></div>",
                 unsafe_allow_html=True)
st.caption("Outfield players only, mean over the tracked seconds of each phase. Outfield block length leaves the "
           "goalkeeper out (SkillCorner's own length includes him). The defensive line is the 4 deepest outfield players.")
say(coach.shape(shape_rows, team, short))

# ---------------------------------------------------------------- pressing (C3)
st.subheader("Pressing")
p = press.assign(team_name=press.team_id.map(short), label=press.window_label + "'")
order = list(p.sort_values("window_index").label.unique())
chart = alt.Chart(p).mark_bar(cornerRadius=2).encode(
    x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelColor=TEXT, labelAngle=0)),
    xOffset=alt.XOffset("team_name:N", sort=[short["HOME"], short["AWAY"]]),
    y=alt.Y("ppp:Q", title="per opponent pass", axis=alt.Axis(labelColor=TEXT, titleColor=TEXT)),
    color=alt.Color("team_id:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None),
    tooltip=[alt.Tooltip("team_name:N", title="team"), alt.Tooltip("label:N", title="minutes"),
             alt.Tooltip("ppp:Q", format=".2f"), alt.Tooltip("defensive_actions:Q", title="defensive actions"),
             alt.Tooltip("opponent_passes:Q", title="opponent passes")]).properties(height=220)
st.altair_chart(chart, width="stretch")
st.caption("Pressures, tackles and fouls per pass of the opponent, per 15 minutes of the football clock (45+ and 90+: "
           "stoppage time). Higher = more intense.")
say(coach.pressing(press, profile, team, short))

# ---------------------------------------------------------------- build-up and attack side (C4, C5)
left, right = st.columns([3, 2])
with left:
    st.subheader("Build-up and attack side")
    b = build.set_index("team_id").loc[team]
    lanes = pd.DataFrame({"lane": ["Left", "Centre", "Right"],
                          "share": [b.share_left, b.share_centre, b.share_right]}).fillna(0)
    st.altair_chart(alt.Chart(lanes).mark_bar(color=colors[team], cornerRadius=3).encode(
        y=alt.Y("lane:N", sort=["Left", "Centre", "Right"], title=None, axis=alt.Axis(labelColor=TEXT)),
        x=alt.X("share:Q", title=None, axis=alt.Axis(format="%", labelColor=TEXT)),
        tooltip=[alt.Tooltip("share:Q", format=".0%")]).properties(height=150), width="stretch")
    st.caption("Successful passes ending in the final third, by lane, seen by the attacking team (left = its left).")
    say(coach.build_up(build, team, short))
with right:
    st.subheader("Space control")
    say(coach.space(space, team, short))
    st.caption("Each 1 m cell of the pitch belongs to the nearest player; the share is averaged over the tracked seconds.")

# ---------------------------------------------------------------- shots and passes (F6)
shots_col, net_col = st.columns(2)
with shots_col:
    st.subheader("Shot map")
    shots = mine("gold_shots")
    views.shot_map("ta_shots", shots, colors)
    bounds = clock_bounds(match)
    st.dataframe(shots[shots.team_id == team].sort_values("ts").assign(
        minute=lambda d: [clock.label(r.ts, r.period, *bounds) for r in d.itertuples()],
        distance=lambda d: d.distance_to_goal_m.round(1))[["minute", "player_name", "type", "distance"]]
        .rename(columns={"player_name": "player", "distance": "distance to goal (m)"}), hide_index=True, width="stretch")
with net_col:
    st.subheader("Pass network")
    card = mine("gold_player_card")
    views.pass_network("ta_network", mine("gold_pass_network"), mine("gold_player_match_stats"), card, team, colors)
    st.caption(f"Each player at his average position; a line = at least {views.MIN_PASSES} passes between two players. "
               "Gold ring: the hub.")
st.caption(CAVEAT)
