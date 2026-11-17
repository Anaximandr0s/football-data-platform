"""Match story (FAN VIEW, docs/product.md: F1, F2, F7, E2, F5, F6): the score and the goals, who was on top every 5
minutes, the 3 biggest differences, the shots and the pass network. Every chart has one plain sentence under it, built
by story.py from the Gold numbers shown."""
import pandas as pd
import streamlit as st

import charts
import clock
import glossary
import sitemap
import story
import views
import viz
from data import CAVEAT, CREDIT, clock_bounds, current_match, require_gold, table

sitemap.header("match_story")
teams = require_gold()
match = current_match(teams)
rows = teams[teams.match_id == match].set_index("team_id")
if {"HOME", "AWAY"} - set(rows.index):
    st.warning(f"{match} does not have both teams in Gold: run `make gold` again.")
    st.stop()
colors = viz.team_colors(teams, match)
names = rows.team_name.to_dict()
short = rows.team_short.to_dict()
home, away = rows.loc["HOME"], rows.loc["AWAY"]

timeline = table("gold_match_timeline")
timeline = timeline[timeline.match_id == match]
profile = table("gold_team_profile")
profile = profile[profile.match_id == match]
shots = table("gold_shots")
shots = shots[shots.match_id == match]
card = table("gold_player_card")
card = card[card.match_id == match]
bounds = clock_bounds(match)
end_minute = float(timeline.window_end_ts.max() / 60)
ticks = clock.axis_ticks(*bounds, end_ts=int(timeline.window_end_ts.max()))
kickoff2 = bounds[1] / 60 if bounds[1] is not None else None
goal_rows = shots[shots.is_goal].sort_values(["ts", "event_id"])
goals = pd.DataFrame({"minute": goal_rows.ts / 60, "team": goal_rows.team_id,
                      "team_name": goal_rows.team_id.map(short),
                      "label": [f"{clock.label(r.ts, r.period, *bounds)} {r.player_short_name} "
                                f"{r.score_home_after}-{r.score_away_after}" for r in goal_rows.itertuples()]})


def say(sentence: story.Sentence | None) -> None:
    if sentence:
        st.markdown(f"<p class='ml-say'>{sentence.text}</p>", unsafe_allow_html=True)


# ---------------------------------------------------------------- score and goals (F1)
st.markdown(f"<div class='ml-scoreline'><span class='team'>{short['HOME']}</span>"
            f"<span class='score'>{home.score} - {away.score}</span>"
            f"<span class='team'>{short['AWAY']}</span></div>", unsafe_allow_html=True)
if goals.empty:
    st.caption("No goal in this match.")
else:
    st.altair_chart(charts.finish(charts.goal_timeline(goals, colors, short, end_minute, ticks, kickoff2)),
                    width="stretch")
say(story.goals(shots, short, (int(home.score), int(away.score)), bounds))

# ---------------------------------------------------------------- who was on top (E2, F2, F1)
st.subheader("Who was on top")
st.markdown("**Danger created with passes**, per 5 minutes")
st.altair_chart(charts.finish(charts.momentum(timeline, goals, colors, short, end_minute, ticks, kickoff2)),
                width="stretch")
st.markdown(f"<div class='ml-meta'>The {glossary.term('xThreat')} of the successful passes: how threatening the targeted "
            "spot was. It is not expected goals (xG).</div>", unsafe_allow_html=True)
say(story.momentum(timeline, short))

st.markdown(f"**Possession**, per 5 minutes: {short['HOME']}'s share")
st.altair_chart(charts.finish(charts.balance(timeline, "possession_share", goals, colors, short, end_minute, ticks,
                                             kickoff2, greyed="possession_greyed")), width="stretch")
st.caption(f"Above 50 %: {short['HOME']} had the ball more; below: {short['AWAY']}. A grey dot: fewer than 60 seconds "
           "with a known owner in that spell, too few to say.")
say(story.possession(timeline, profile, short))

st.markdown(f"**Territory** ({glossary.term('field tilt')}), per 5 minutes: {short['HOME']}'s share of the passes "
            "played near the opponent's goal", unsafe_allow_html=True)
st.altair_chart(charts.finish(charts.balance(timeline, "field_tilt", goals, colors, short, end_minute, ticks,
                                             kickoff2)), width="stretch")
st.caption(f"Above 50 %: {short['HOME']} played more in the other half; below: {short['AWAY']}. A grey dot: no such "
           "pass in that spell.")
say(story.field_tilt(timeline, profile, short))

# ---------------------------------------------------------------- 3 key differences (F7)
st.subheader("Three key differences")
for col, sentence in zip(st.columns(3), story.key_differences(profile, short), strict=False):
    col.markdown(f"<div class='ml-card'><p>{sentence.text}</p></div>", unsafe_allow_html=True)
st.caption("The three largest gaps between the teams. They describe the match; they do not say why it ended this way.")

# ---------------------------------------------------------------- shots and passes (F6)
left, right = st.columns(2)
with left:
    st.subheader("Shots")
    views.shot_map("story_shots", shots, colors)
    st.caption(f"Filled with a gold ring: goal. {short['HOME']} attacks to the right, {short['AWAY']} to the left.")
    say(story.shots_line(shots, short))
with right:
    st.subheader("Pass network")
    side = st.segmented_control("Team", ["HOME", "AWAY"], default="HOME", format_func=short.get,
                                key="story_net_team") or "HOME"
    net = table("gold_pass_network")
    stats = table("gold_player_match_stats")
    views.pass_network("story_network", net[net.match_id == match], stats[stats.match_id == match], card, side, colors)
    st.caption(f"Each player at his average position; a line = at least {views.MIN_PASSES} passes between two players, "
               "thicker = more. Gold ring: the hub.")
    say(story.hub(card, side, short))

# ---------------------------------------------------------------- side by side (F5)
st.subheader("Side by side")
top = card.groupby("team_id").top_speed_kmh.max()
prof = profile.set_index("team_id")
table_rows = {
    "Possession": [f"{prof.loc[t, 'possession_share']:.0%}" for t in ("HOME", "AWAY")],
    "Shots (goals included)": [f"{int(prof.loc[t, 'shots_and_goals'])}" for t in ("HOME", "AWAY")],
    "Passes (successful)": [f"{int(rows.loc[t, 'passes'])} ({int(rows.loc[t, 'passes_successful'])})"
                            for t in ("HOME", "AWAY")],
    "Distance (km, tracked time)": [f"{rows.loc[t, 'distance_km']:.1f}" for t in ("HOME", "AWAY")],
    "Sprint efforts": [f"{int(rows.loc[t, 'sprint_count'])}" for t in ("HOME", "AWAY")],
    "Top speed (km/h, held 2 s)": [f"about {top[t]:.0f}" if pd.notna(top.get(t)) else "n/a" for t in ("HOME", "AWAY")],
}
st.dataframe(pd.DataFrame(table_rows, index=[short["HOME"], short["AWAY"]]).T, width="stretch")
say(story.fastest(card, short))
with st.expander("How to read these numbers"):
    st.markdown(CAVEAT)
st.caption(CREDIT)
