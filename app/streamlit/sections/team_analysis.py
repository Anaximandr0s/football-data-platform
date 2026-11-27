"""Team analysis (COACH VIEW, docs/product.md: C1-C5, S1, F6): how one team organises with and without the ball,
presses, builds up and attacks, with the shot map and the pass network. One sentence under each part, built by
coach.py from the Gold numbers shown."""

import altair as alt
import pandas as pd
import streamlit as st

import charts
import clock
import coach
import glossary
import sitemap
import views
import viz
from data import CAVEAT, clock_bounds, current_match, require_gold, table

PHASES = {
    "in_possession": "With the ball",
    "out_of_possession": "Without the ball",
    "unknown": "Ball dead or contested",
}


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


profile, shape_rows, press, build, space = (
    mine(t)
    for t in ("gold_team_profile", "gold_team_shape", "gold_pressing", "gold_team_build_up", "gold_space_control")
)

# ---------------------------------------------------------------- shape (C1, C2)
st.subheader("Shape")
s = shape_rows[shape_rows.team_id == team].set_index("phase")
cols = st.columns(3)
for col, (phase, title) in zip(cols, PHASES.items(), strict=True):
    if phase not in s.index:
        continue
    r = s.loc[phase]
    col.markdown(
        f"<div class='ml-card'><div class='ml-kicker'>{title.upper()}</div>"
        f"<div class='ml-stats'><div><span>Width</span><b>{r.width:.0f} m</b></div>"
        f"<div><span>{glossary.term('outfield block', 'Outfield block')} length</span><b>{r.length:.0f} m</b></div>"
        f"<div><span>Defensive line from own goal</span><b>{r.defensive_line_height:.0f} m</b></div>"
        f"<div><span>Based on</span><b>{r.seconds_used / 60:.0f} minutes</b></div></div>"
        f"<div class='ml-meta'>{r.detected_share:.0%} of the positions seen by the camera</div></div>",
        unsafe_allow_html=True,
    )
st.caption(
    "Outfield players only, mean over the tracked minutes of each phase. The outfield block leaves the "
    "goalkeeper out (SkillCorner's own length includes him). The defensive line is the 4 deepest outfield players."
)
say(coach.shape(shape_rows, team, short))

# ---------------------------------------------------------------- pressing (C3)
st.subheader("Pressing")
p = press.assign(
    team_name=press.team_id.map(short),
    label=press.window_label + "'",
    note=press.ppp_greyed.map({True: "too few passes", False: ""}),
)
order = list(p.sort_values("window_index").label.unique())
st.markdown(
    views.team_key(colors, short) + "<span class='ml-key'><i style='border:2px solid currentColor'></i>"
    "empty outline: too few opponent passes to trust</span>",
    unsafe_allow_html=True,
)
x = alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0))
offset = alt.XOffset("team_name:N", sort=[short["HOME"], short["AWAY"]])
team_color = alt.Color("team_id:N", scale=alt.Scale(domain=list(colors), range=list(colors.values())), legend=None)
tips = [
    alt.Tooltip("team_name:N", title="team"),
    alt.Tooltip("label:N", title="minutes"),
    alt.Tooltip("ppp:Q", format=".2f"),
    alt.Tooltip("defensive_actions:Q", title="defensive actions"),
    alt.Tooltip("opponent_passes:Q", title="opponent passes"),
]
base = alt.Chart(p).encode(x=x, xOffset=offset, y=alt.Y("ppp:Q", title="actions per opponent pass"), tooltip=tips)
full = base.transform_filter("!datum.ppp_greyed").mark_bar(cornerRadius=2).encode(color=team_color)
empty = (
    base.transform_filter("datum.ppp_greyed")
    .mark_bar(cornerRadius=2, fillOpacity=0, strokeWidth=2, strokeDash=[4, 3])
    .encode(stroke=team_color)
)
note = (
    base.transform_filter("datum.ppp_greyed").mark_text(dy=-10, fontSize=13, fontStyle="italic").encode(text="note:N")
)
st.altair_chart(charts.finish(alt.layer(full, empty, note).properties(height=240)), width="stretch")
st.markdown(
    f"<div class='ml-meta'>{glossary.term('pressing', 'Pressing')}: pressures, tackles and fouls per pass of the "
    "opponent, per 15 minutes of the football clock (45+ and 90+: stoppage time). Higher = more intense.</div>",
    unsafe_allow_html=True,
)
say(coach.pressing(press, profile, team, short))

# ---------------------------------------------------------------- build-up and attack side (C4, C5)
left, right = st.columns([3, 2])
with left:
    st.subheader("Build-up and attack side")
    b = build.set_index("team_id").loc[team]
    lanes = pd.DataFrame(
        {"lane": ["Left", "Centre", "Right"], "share": [b.share_left, b.share_centre, b.share_right]}
    ).fillna(0)
    lane_base = alt.Chart(lanes).encode(
        y=alt.Y("lane:N", sort=["Left", "Centre", "Right"], title=None),
        x=alt.X("share:Q", title=None, axis=alt.Axis(format="%")),
    )
    st.altair_chart(
        charts.finish(
            (
                lane_base.mark_bar(color=colors[team], cornerRadius=3)
                + lane_base.mark_text(align="left", dx=4, fontSize=charts.FONT).encode(
                    text=alt.Text("share:Q", format=".0%")
                )
            ).properties(height=160)
        ),
        width="stretch",
    )
    st.caption("Successful passes ending in the final third, by lane, seen by the attacking team (left = its left).")
    say(coach.build_up(build, team, short))
with right:
    st.subheader("Space control")
    say(coach.space(space, team, short))
    st.markdown(
        f"<div class='ml-meta'>{glossary.term('space control', 'Space control')}: each 1 m cell of the pitch "
        f"belongs to the nearest player; the share is averaged over the {glossary.term('tracked')} seconds."
        "</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------- shots and passes (F6)
shots_col, net_col = st.columns(2)
with shots_col:
    st.subheader("Shot map")
    shots = mine("gold_shots")
    views.shot_map("ta_shots", shots, colors)
    bounds = clock_bounds(match)
    st.dataframe(
        shots[shots.team_id == team]
        .sort_values("ts")
        .assign(
            minute=lambda d: [clock.label(r.ts, r.period, *bounds) for r in d.itertuples()],
            distance=lambda d: d.distance_to_goal_m.round(1),
        )[["minute", "player_name", "type", "distance"]]
        .rename(columns={"player_name": "player", "distance": "distance to goal (m)"}),
        hide_index=True,
        width="stretch",
    )
with net_col:
    st.subheader("Pass network")
    card = mine("gold_player_card")
    views.pass_network("ta_network", mine("gold_pass_network"), mine("gold_player_match_stats"), card, team, colors)
    st.caption(
        f"Each player at his average position; a line = at least {views.MIN_PASSES} passes between two players. "
        "Gold ring: the hub."
    )
st.caption(CAVEAT)
