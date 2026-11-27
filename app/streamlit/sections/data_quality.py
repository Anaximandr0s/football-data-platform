"""Data quality (BEHIND THE DATA): can I trust these numbers? Six dimensions (completeness, uniqueness, validity,
consistency, accuracy, freshness), each with a simple question and one number, then the evidence: a match x dimension
grid, the camera coverage, the pipeline runs, what our checks caught, and every check. Logic in quality.py."""

from datetime import UTC, datetime

import altair as alt
import pandas as pd
import streamlit as st

import charts
import quality
import sitemap
import theme
from data import (
    CREDIT,
    dbt_tests,
    dimension_map,
    external_checks,
    library,
    pipeline_file,
    quality_evidence,
    replay_counts,
    silver_reports,
    soda_results,
    table,
)

COLOR = {status: theme.STATUS[status] for status in (quality.GREEN, quality.ORANGE, quality.RED, quality.GREY)}
MATCH_COLORS = ["#009E73", "#CC79A7", "#E69F00", "#56B4E9"]  # Okabe-Ito, not the team pair
WORD = {quality.GREEN: "good", quality.ORANGE: "fixed or close", quality.RED: "problem", quality.GREY: "no data"}

sitemap.header("data_quality")
# light or dark page: text keeps the theme's colour, the status is a coloured edge and a filled label with dark text
st.markdown(
    f"""<style>
.dq-banner{{padding:14px 18px;border-radius:10px;font-size:1.1rem;font-weight:700;margin:.3rem 0 1rem 0;
  color:{theme.ON_FILL}}}
.dq-card{{border:1px solid rgba(127,127,127,.35);border-left:8px solid var(--c);border-radius:10px;padding:12px 14px;
  background:rgba(127,127,127,.06);height:100%}}
.dq-card h4{{margin:0;font-size:1.1rem}} .dq-card .fr{{opacity:{theme.MUTED_OPACITY};font-weight:500;font-size:.95rem}}
.dq-card .q{{opacity:{theme.MUTED_OPACITY};font-size:.98rem;margin:.15rem 0 .5rem 0}}
.dq-card .n{{font-size:2.1rem;font-weight:800;line-height:1.1}}
.dq-card .s{{display:inline-block;background:var(--c);color:{theme.ON_FILL};font-weight:700;font-size:.85rem;
  border-radius:999px;padding:.05rem .55rem;margin-left:.5rem;vertical-align:middle}}
.dq-card ul{{margin:.4rem 0 0 1rem;padding:0;font-size:.95rem}} .dq-card li{{margin:.15rem 0}}
.dq-caught{{border:1px solid rgba(127,127,127,.35);border-radius:10px;padding:10px 14px;background:rgba(127,127,127,.06);
  margin-bottom:8px}}
</style>""",
    unsafe_allow_html=True,
)

results, mapping, lib = soda_results(), dimension_map(), library()
if not results or lib is None:
    st.info(
        "No quality result yet: run `make gold` and `make soda` (they write `data/soda/silver.json` and "
        "`data/soda/gold.json`)."
    )
    st.stop()
checks = quality.checks_table(results, mapping)
last = max(r["finished_at_utc"] for r in results.values())
last_text = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(UTC).strftime("%d %b %Y %H:%M UTC")
matches = sorted(lib.match_id)
runs = pipeline_file("runs") or []
evidence = quality_evidence()
kept = quality.kept(silver_reports(), replay_counts())
external = external_checks()
acc = (
    quality.accuracy(external, table("gold_events"), lib, table("gold_team_profile"))
    if external
    else pd.DataFrame(columns=["match_id", "what", "ours", "sources", "status", "scorer_agrees"])
)

status, sentence = quality.verdict(checks, last_text, len(matches))
st.markdown(
    f"<div class='dq-banner' style='background:{COLOR[status]}'>{'✔' if status == quality.GREEN else '✖'} "
    f"{sentence}</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- the six dimensions
cards = quality.cards(checks, kept, lib, acc, runs, dbt_tests(), evidence, last_text)
for row in (cards[:3], cards[3:]):
    for col, card in zip(st.columns(3), row, strict=True):
        col.markdown(
            f"<div class='dq-card' style='--c:{COLOR[card.status]}'><h4>{card.dimension.capitalize()} "
            f"<span class='fr'>· {quality.FRENCH[card.dimension]}</span></h4>"
            f"<div class='q'>{quality.QUESTION[card.dimension]}</div><div class='n'>{card.number}"
            f"<span class='s'>{WORD[card.status]}</span></div>"
            f"<ul>{''.join(f'<li>{line}</li>' for line in card.lines)}</ul></div>",
            unsafe_allow_html=True,
        )
    st.write("")
st.caption(
    "Green: good. Orange: values our pipeline fixed, or close to the official reports. Red: a problem to fix "
    "before trusting the numbers. Grey: nothing measured yet."
)

# ---------------------------------------------------------------- per match
st.subheader("Each match, each dimension")
names = {r.match_id: f"{r.home_team_short} {r.home_score}-{r.away_score} {r.away_team_short}" for r in lib.itertuples()}
grid = quality.grid(matches, checks, kept, acc, runs).melt("match_id", var_name="dimension", value_name="status")
grid["match"] = grid.match_id.map(names)
grid["meaning"] = grid.status.map(WORD)
grid["label"] = grid.dimension.map(lambda d: f"{d.capitalize()} · {quality.FRENCH[d]}")
order = [f"{d.capitalize()} · {quality.FRENCH[d]}" for d in quality.DIMENSIONS]
heat = (
    alt.Chart(grid)
    .mark_rect(cornerRadius=4, stroke="#8a948f", strokeWidth=1.5)
    .encode(
        x=alt.X(
            "label:N",
            sort=order,
            title=None,
            axis=alt.Axis(
                labelAngle=0, labelLimit=0, orient="top", labelOverlap=False, labelExpr="split(datum.value, ' · ')"
            ),
        ),
        y=alt.Y("match:N", title=None, axis=alt.Axis(labelLimit=300)),
        color=alt.Color("status:N", scale=alt.Scale(domain=list(COLOR), range=list(COLOR.values())), legend=None),
        tooltip=["match:N", "label:N", "meaning:N"],
    )
)
text = (
    alt.Chart(grid)
    .mark_text(color=theme.ON_FILL, fontWeight="bold", fontSize=charts.FONT)
    .encode(x=alt.X("label:N", sort=order), y="match:N", text="meaning:N")
)
st.altair_chart(charts.finish((heat + text).properties(height=64 * len(matches))), width="stretch")
st.caption(
    "Completeness judges our pipeline (what we kept), not the camera. Validity is orange when Silver had to put "
    "positions back on the pitch or remove impossible speeds: nothing wrong is left. Freshness: green when Gold "
    "was rebuilt within 10 minutes of the latest replay's final whistle, red when Gold is older than it."
)

left, right = st.columns(2)
with left:
    st.markdown("**What the camera saw, every 5 minutes**")
    space = table("gold_space_control")
    cov = space[space.team_id == "HOME"].assign(
        match=lambda d: d.match_id.map(names), seen=lambda d: d.seconds_used / d.window_seconds
    )
    st.altair_chart(
        charts.finish(
            alt.Chart(cov)
            .mark_line(point=True, strokeWidth=2.5)
            .encode(
                x=alt.X("window_index:O", title=None, axis=alt.Axis(labelExpr="''", ticks=False)),
                y=alt.Y("seen:Q", title="seen", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")),
                color=alt.Color(
                    "match:N",
                    scale=alt.Scale(range=MATCH_COLORS),
                    legend=alt.Legend(orient="bottom", columns=1, title=None, labelLimit=0),
                ),
                tooltip=[
                    "match:N",
                    alt.Tooltip("window_label:N", title="minutes"),
                    alt.Tooltip("seen:Q", format=".0%"),
                ],
            )
            .properties(height=440)
        ),
        width="stretch",
    )  # the height holds the legend too
    st.caption(
        "Tracked seconds of each 5-minute window (0-5' ... 45+, 45-50' ... 90+), from left to right. The gaps are "
        "mostly dead-ball moments without a TV picture of the pitch: a limit of the source, shown, not judged."
    )
with right:
    st.markdown("**The last pipeline runs** (Dagster)")
    pr = pd.DataFrame(
        [
            {
                "match": names.get(r.get("match_id"), r.get("match_id") or "all"),
                "started": pd.to_datetime(r["started"], unit="s", utc=True),
                "result": "passed" if r["status"] == "SUCCESS" else "failed",
                "trigger": r["trigger"],
                "minutes": round((r["ended"] - r["started"]) / 60, 1) if r.get("ended") else None,
            }
            for r in runs
            if r.get("started")
        ]
    )
    if pr.empty:
        st.info("No Dagster run yet: `make dagster`, then replay a match.")
    else:
        st.altair_chart(
            charts.finish(
                alt.Chart(pr)
                .mark_point(size=220, filled=True)
                .encode(
                    x=alt.X("started:T", title=None, axis=alt.Axis(format="%d %b %H:%M")),
                    y=alt.Y("match:N", title=None, axis=alt.Axis(labelLimit=260)),
                    color=alt.Color(
                        "result:N",
                        scale=alt.Scale(domain=["passed", "failed"], range=[COLOR[quality.GREEN], COLOR[quality.RED]]),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    shape=alt.Shape(
                        "result:N", scale=alt.Scale(domain=["passed", "failed"], range=["circle", "cross"]), legend=None
                    ),
                    tooltip=["match:N", "started:T", "result:N", "trigger:N", "minutes:Q"],
                )
                .properties(height=260)
            ),
            width="stretch",
        )
        st.caption("Each dot is one run of the chain of a match: Bronze, Silver, Soda, Gold, Soda, report.")

# ---------------------------------------------------------------- what our checks stopped
st.subheader("Caught by our checks")
caught = quality.caught(runs, evidence)
if not caught:
    st.caption("No failed run yet.")
for c in caught:
    fix = f" Fixed in commit <code>{c['fix']}</code>." if c["fix"] else ""
    st.markdown(
        f"<div class='dq-caught'><b>{c['match_id'] or ''} · run {c['run']}</b> stopped at "
        f"<code>{c['stopped_at'] or '?'}</code>{' · not built: ' + c['not_built'] if c['not_built'] else ''}"
        f"<br>{c['what']}{fix}</div>",
        unsafe_allow_html=True,
    )
if evidence:
    st.caption(
        f"Explanations and proofs from `make evidence`, {evidence['generated_at']}, commit {evidence['commit']}."
    )
else:
    st.caption("Run `make evidence` to add the explanations and the Live and Streaming proofs.")

# ---------------------------------------------------------------- details
with st.expander("Accuracy: our numbers against the official reports"):
    if acc.empty:
        st.info("docs/external_checks.yml is missing.")
    else:
        st.dataframe(
            acc.assign(
                match=acc.match_id.map(names),
                result=acc.status.map(
                    {
                        quality.GREEN: "same as a source",
                        quality.ORANGE: "1 minute / 2 points away",
                        quality.RED: "further",
                    }
                ),
            )[["match", "what", "ours", "sources", "result"]],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            f"Sources and links: `docs/external_checks.yml`, checked {external['checked_on']}. A minute is exact "
            "when at least one source gives it: the sources themselves disagree (Goodwin 62' or 63', Klein 50' "
            "or 51')."
        )

with st.expander(f"All {len(checks)} checks"):
    f1, f2, f3 = st.columns(3)
    dims = f1.multiselect("Dimension", sorted(checks.dimension.unique()))
    layers = f2.multiselect("Layer", sorted(checks.layer.unique()))
    res = f3.multiselect("Result", sorted(checks.result.unique()))
    shown = checks
    for col, chosen in (("dimension", dims), ("layer", layers), ("result", res)):
        if chosen:
            shown = shown[shown[col].isin(chosen)]
    st.dataframe(
        shown[["check", "dimension", "layer", "table", "result", "detail"]],
        hide_index=True,
        width="stretch",
        height=420,
    )
    st.caption("The dimension of each check: `soda/dimensions.yml` (a test makes sure no check is left without one).")
st.caption(CREDIT)
