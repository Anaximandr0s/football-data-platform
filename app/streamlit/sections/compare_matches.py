"""Compare matches (MATCHES, docs/product.md: C7, F7): one team in any of its stored matches, side by side, with the
result, the opponent and the venue named. A radar shows the profile at a glance, then every metric as small bars in four
groups, each with its value written and what "higher" means. Only team profiles are compared across matches."""
import math

import altair as alt
import pandas as pd
import streamlit as st

import charts
import coach
import sitemap
from data import CAVEAT, library, require_gold, table

# metric -> (title, format, what a higher value means, group)
METRICS = {
    "possession_share": ("Possession", "{:.0%}", "more of the ball", "With the ball"),
    "field_tilt": ("Field tilt", "{:.0%}", "more passes in the opponent's third", "With the ball"),
    "shots_and_goals": ("Shots (goals included)", "{:.0f}", "more shots", "With the ball"),
    "progressive_passes_per90": ("Passes 10 m+ toward goal, per 90 min", "{:.0f}", "more forward passing",
                                 "With the ball"),
    "ppp": ("Pressing: actions per opponent pass", "{:.2f}", "more intense pressing", "Without the ball"),
    "high_press_share": ("Pressing in the final third", "{:.0%}", "pressing higher up the pitch", "Without the ball"),
    "width": ("Width", "{:.0f} m", "a wider team", "Shape"),
    "length": ("Outfield block length", "{:.0f} m", "a longer, more stretched block", "Shape"),
    "defensive_line_height": ("Defensive line from own goal", "{:.0f} m", "a higher defensive line", "Shape"),
    "dpm_outfield": ("Distance per tracked minute", "{:.0f} m", "more running", "Physical"),
}
GROUPS = ["With the ball", "Without the ball", "Shape", "Physical"]
MATCH_COLORS = ["#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000"]   # Okabe-Ito, not the team pair

sitemap.header("compare_matches")
teams = require_gold()
profile = table("gold_team_profile")
lib = library()
dates = {} if lib is None else dict(zip(lib.match_id, lib.match_date, strict=True))
fans = teams[["match_id", "team_id", "team_short", "score", "opponent_score"]]
all_rows = profile.copy()
profile = profile.merge(fans, on=["match_id", "team_id"])
names = sorted(profile.team_short.unique())
default_team = "Brisbane Roar" if "Brisbane Roar" in names else names[0]
team_name = st.selectbox("Team", names, index=names.index(default_team))
mine = profile[profile.team_short == team_name].copy()
opponent = {r.match_id: teams[(teams.match_id == r.match_id) & (teams.team_id != r.team_id)].team_short.iloc[0]
            for r in mine.itertuples()}
mine["opponent"] = mine.match_id.map(opponent)


def label(r) -> str:
    result = "W" if r.score > r.opponent_score else "L" if r.score < r.opponent_score else "D"
    where = f"at home v {r.opponent}" if r.team_id == "HOME" else f"away at {r.opponent}"
    return f"{result} {r.score}-{r.opponent_score} · {where}"


labels = {r.match_id: label(r) for r in mine.itertuples()}
# the sentences open with the match: "away at Perth Glory (3-1), Brisbane Roar ..."
spoken = {r.match_id: (f"at home against {r.opponent}" if r.team_id == "HOME" else f"away at {r.opponent}")
          + f" ({r.score}-{r.opponent_score})" for r in mine.itertuples()}
heads = {m: labels[m] + (f" · {dates[m]:%d %b %Y}" if m in dates else "") for m in labels}
ids = sorted(labels, key=lambda m: dates.get(m, m))
perth = [m for m in ids if opponent[m] == "Perth Glory"] if team_name == "Brisbane Roar" else []
chosen = st.multiselect("Matches", ids, default=perth if len(perth) >= 2 else ids[:2], format_func=heads.get)
if len(chosen) < 2:
    st.info(f"{team_name} has {len(ids)} stored match{'es' if len(ids) != 1 else ''}: pick at least two to compare."
            if len(ids) >= 2 else f"{team_name} has only one stored match.")
    st.stop()

picked = mine.set_index("match_id").loc[chosen].reset_index()
picked["match"] = picked.match_id.map(heads)
palette = dict(zip([heads[m] for m in chosen], MATCH_COLORS, strict=False))
match_color = alt.Color("match:N", scale=alt.Scale(domain=list(palette), range=list(palette.values())),
                        legend=alt.Legend(orient="bottom", direction="vertical", title=None, labelLimit=0))


def radar(rows: pd.DataFrame) -> alt.Chart:
    """One polygon per match. Each axis runs from the lowest to the highest value of all teams in all stored matches,
    so a shape does not depend on which matches are compared."""
    keys = [k for k in METRICS if k in rows and all_rows[k].notna().any()]
    lo, hi = all_rows[keys].min(), all_rows[keys].max()
    pts, axes = [], []
    for i, k in enumerate(keys):
        angle = math.pi / 2 - 2 * math.pi * i / len(keys)
        axes.append({"x": math.cos(angle), "y": math.sin(angle), "lx": 1.22 * math.cos(angle),
                     "ly": 1.15 * math.sin(angle), "text": METRICS[k][0], "x0": 0, "y0": 0})
        for _, r in rows.iterrows():
            v = 0.0 if pd.isna(r[k]) or hi[k] == lo[k] else (r[k] - lo[k]) / (hi[k] - lo[k])
            pts.append({"match": r.match, "order": i, "x": v * math.cos(angle), "y": v * math.sin(angle),
                        "metric": METRICS[k][0], "value": METRICS[k][1].format(r[k]) if pd.notna(r[k]) else "–"})
    pts = pd.DataFrame(pts)
    first = pts[pts.order == 0].assign(order=len(keys))           # close each polygon
    pts = pd.concat([pts, first])
    scale = alt.Scale(domain=[-1.45, 1.45])
    xy = {"x": alt.X("x:Q", scale=scale, axis=None), "y": alt.Y("y:Q", scale=scale, axis=None)}
    rings = pd.DataFrame([{"x": r * math.cos(t / 60 * 2 * math.pi), "y": r * math.sin(t / 60 * 2 * math.pi),
                           "ring": r, "t": t} for r in (0.5, 1.0) for t in range(61)])
    grid = alt.Chart(rings).mark_line(color=charts.LINE, opacity=0.5, strokeDash=[2, 3]).encode(
        **xy, detail="ring:N", order="t:Q")
    spokes = alt.Chart(pd.DataFrame(axes)).mark_rule(color=charts.LINE, opacity=0.5).encode(
        x=alt.X("x0:Q", scale=scale, axis=None), y=alt.Y("y0:Q", scale=scale, axis=None), x2="x:Q", y2="y:Q")
    words = alt.Chart(pd.DataFrame(axes)).mark_text(fontSize=charts.FONT - 1, fontWeight="bold").encode(
        x=alt.X("lx:Q", scale=scale, axis=None), y=alt.Y("ly:Q", scale=scale, axis=None), text="text:N")
    shapes = alt.Chart(pts).mark_line(strokeWidth=3, point=alt.OverlayMarkDef(size=60)).encode(
        **xy, color=match_color, order="order:Q",
        tooltip=[alt.Tooltip("match:N"), alt.Tooltip("metric:N"), alt.Tooltip("value:N")])
    return alt.layer(grid, spokes, shapes, words).properties(height=460)


st.altair_chart(charts.finish(radar(picked)), width="stretch")
st.caption("Each axis goes from the lowest (centre) to the highest value (edge) of all teams in all stored matches. "
           "A bigger shape is not \"better\": it says where the team stood on each axis.")

say = coach.compare(picked, spoken, team_name)
for col, sentence in zip(st.columns(len(say)) if say else [], say, strict=False):
    col.markdown(f"<div class='ml-card'><p>{sentence.text}</p></div>", unsafe_allow_html=True)
st.caption("The metrics that changed most between the first two matches chosen. Each match had its own opponent and "
           "venue: these are differences, not causes.")

long = picked.melt(id_vars=["match"], value_vars=list(METRICS), var_name="metric", value_name="value")
long["text"] = [METRICS[m][1].format(v) if pd.notna(v) else "–" for m, v in zip(long.metric, long.value, strict=True)]
long["title"] = long.metric.map(lambda m: f"{METRICS[m][0]}|higher = {METRICS[m][2]}")
long["group"] = long.metric.map(lambda m: METRICS[m][3])
long["value"] = long.value.fillna(0)
for group in GROUPS:
    part = long[long.group == group]
    st.subheader(group)
    base = alt.Chart().encode(y=alt.Y("match:N", title=None, sort=[heads[m] for m in chosen], axis=None),
                              x=alt.X("value:Q", title=None, axis=None))
    bars = base.mark_bar(cornerRadius=3, height=22).encode(color=match_color, tooltip=["match:N", "text:N"])
    values = base.mark_text(align="left", dx=5, fontSize=charts.FONT, fontWeight="bold").encode(text="text:N")
    order = [f"{METRICS[m][0]}|higher = {METRICS[m][2]}" for m in METRICS if METRICS[m][3] == group]
    chart = alt.layer(bars, values, data=part).properties(width=230, height=32 * len(chosen)).facet(
        facet=alt.Facet("title:N", sort=order, title=None,
                        header=alt.Header(labelExpr="split(datum.value, '|')", labelFontSize=charts.FONT,
                                          labelFontWeight="bold", labelAlign="left", labelAnchor="start")),
        columns=3).resolve_scale(x="independent")
    st.altair_chart(charts.finish(chart), width="content")
st.caption(CAVEAT)
