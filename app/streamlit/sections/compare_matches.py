"""Compare matches (MATCHES, docs/product.md: C7, F7): one team in any of its stored matches, side by side, with the
opponent and the venue named. Scores and ranks stay inside each match; only team profiles are compared across them."""
import altair as alt
import pandas as pd
import streamlit as st

import coach
import sitemap
from charts import TEXT
from data import CAVEAT, library, require_gold, table

METRICS = {
    "possession_share": ("Possession", "{:.0%}"), "field_tilt": ("Passes from the final third (field tilt)", "{:.0%}"),
    "shots_and_goals": ("Shots (goals included)", "{:.0f}"), "width": ("Width (m)", "{:.0f}"),
    "length": ("Outfield block length (m)", "{:.0f}"), "defensive_line_height": ("Defensive line from own goal (m)",
                                                                                 "{:.0f}"),
    "ppp": ("Pressing: actions per opponent pass", "{:.2f}"), "high_press_share": ("Pressing in the final third",
                                                                                 "{:.0%}"),
    "progressive_passes_per90": ("Passes of 10 m+ toward goal, per 90 tracked min", "{:.0f}"),
    "dpm_outfield": ("Distance per minute of tracked play (m)", "{:.0f}"),
    "share_left": ("Final-third entries on the left", "{:.0%}"), "share_centre": ("... in the centre", "{:.0%}"),
    "share_right": ("... on the right", "{:.0%}"),
}

sitemap.header("compare_matches")
teams = require_gold()
profile = table("gold_team_profile")
lib = library()
dates = {} if lib is None else dict(zip(lib.match_id, lib.match_date, strict=True))
fans = teams[["match_id", "team_id", "team_short", "score", "opponent_score"]]
profile = profile.merge(fans, on=["match_id", "team_id"])
names = sorted(profile.team_short.unique())
default_team = "Brisbane Roar" if "Brisbane Roar" in names else names[0]
team_name = st.selectbox("Team", names, index=names.index(default_team))
mine = profile[profile.team_short == team_name].copy()
opponent = {r.match_id: teams[(teams.match_id == r.match_id) & (teams.team_id != r.team_id)].team_short.iloc[0]
            for r in mine.itertuples()}
mine["opponent"] = mine.match_id.map(opponent)


def label(r) -> str:
    where = f"at home against {r.opponent}" if r.team_id == "HOME" else f"away at {r.opponent}"
    return f"{where} ({r.score}-{r.opponent_score})"


labels = {r.match_id: label(r) for r in mine.itertuples()}
heads = {m: (f"{dates[m]:%d %b %Y} · " if m in dates else "") + labels[m] for m in labels}
ids = sorted(labels, key=lambda m: dates.get(m, m))
perth = [m for m in ids if opponent[m] == "Perth Glory"] if team_name == "Brisbane Roar" else []
chosen = st.multiselect("Matches", ids, default=perth if len(perth) >= 2 else ids[:2], format_func=heads.get)
if len(chosen) < 2:
    st.info(f"{team_name} has {len(ids)} stored match{'es' if len(ids) != 1 else ''}: pick at least two to compare."
            if len(ids) >= 2 else f"{team_name} has only one stored match.")
    st.stop()

picked = mine.set_index("match_id").loc[chosen].reset_index()
say = coach.compare(picked, labels, team_name)
for col, sentence in zip(st.columns(len(say)) if say else [], say, strict=False):
    col.markdown(f"<div class='ml-card'><p>{sentence.text}</p></div>", unsafe_allow_html=True)
st.caption("The metrics that changed most between the first two matches chosen. Each match had its own opponent and "
           "venue: these are differences, not causes.")

rows = {title: [fmt.format(v) if pd.notna(v) else "–" for v in picked[metric]] for metric, (title, fmt) in
        METRICS.items()}
st.dataframe(pd.DataFrame(rows, index=[heads[m] for m in chosen]).T, width="stretch")

metric = st.selectbox("Chart", list(METRICS), format_func=lambda m: METRICS[m][0])
bars = picked.assign(match=[heads[m] for m in chosen])
st.altair_chart(alt.Chart(bars).mark_bar(cornerRadius=3, color="#3ddc84").encode(
    y=alt.Y("match:N", title=None, sort=[heads[m] for m in chosen], axis=alt.Axis(labelColor=TEXT, labelLimit=420)),
    x=alt.X(f"{metric}:Q", title=METRICS[metric][0], axis=alt.Axis(labelColor=TEXT, titleColor=TEXT)),
    tooltip=[alt.Tooltip("match:N"), alt.Tooltip(f"{metric}:Q", format=".2f")]).properties(height=60 * len(chosen)),
    width="stretch")
st.caption(CAVEAT)
