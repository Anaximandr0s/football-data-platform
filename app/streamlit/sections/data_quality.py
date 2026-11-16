"""Data quality (BEHIND THE DATA): can I trust these numbers? Six dimensions (completeness, uniqueness, validity,
consistency, accuracy, freshness), each with a simple question and one number, then the evidence: a match x dimension
grid, the camera coverage, the pipeline runs, what our checks caught, and every check. Logic in quality.py."""
from datetime import UTC, datetime

import altair as alt
import pandas as pd
import streamlit as st

import quality
import sitemap
from charts import TEXT
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

COLOR = {quality.GREEN: "#3ddc84", quality.ORANGE: "#f4a340", quality.RED: "#e5484d", quality.GREY: "#5b6b62"}
WORD = {quality.GREEN: "good", quality.ORANGE: "fixed or close", quality.RED: "problem", quality.GREY: "no data"}

sitemap.header("data_quality")
st.markdown("""<style>
.dq-banner{padding:14px 18px;border-radius:10px;font-size:1.05rem;font-weight:700;margin:.3rem 0 1rem 0}
.dq-card{border:1px solid #23392d;border-left:6px solid var(--c);border-radius:10px;padding:12px 14px;
  background:#12221a;height:100%}
.dq-card h4{margin:0;font-size:1.02rem} .dq-card .fr{color:#b9c8bf;font-weight:500;font-size:.85rem}
.dq-card .q{color:#b9c8bf;font-size:.88rem;margin:.15rem 0 .5rem 0}
.dq-card .n{font-size:2rem;font-weight:800;line-height:1.1;color:var(--c)}
.dq-card ul{margin:.4rem 0 0 1rem;padding:0;font-size:.85rem;color:#e8f0ea} .dq-card li{margin:.15rem 0}
.dq-caught{border:1px solid #23392d;border-radius:10px;padding:10px 14px;background:#12221a;margin-bottom:8px}
</style>""", unsafe_allow_html=True)

results, mapping, lib = soda_results(), dimension_map(), library()
if not results or lib is None:
    st.info("No quality result yet: run `make gold` and `make soda` (they write `data/soda/silver.json` and "
            "`data/soda/gold.json`).")
    st.stop()
checks = quality.checks_table(results, mapping)
last = max(r["finished_at_utc"] for r in results.values())
last_text = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(UTC).strftime("%d %b %Y %H:%M UTC")
matches = sorted(lib.match_id)
runs = pipeline_file("runs") or []
evidence = quality_evidence()
kept = quality.kept(silver_reports(), replay_counts())
external = external_checks()
acc = quality.accuracy(external, table("gold_events"), lib, table("gold_team_profile")) if external else \
    pd.DataFrame(columns=["match_id", "what", "ours", "sources", "status", "scorer_agrees"])

status, sentence = quality.verdict(checks, last_text, len(matches))
st.markdown(f"<div class='dq-banner' style='background:{COLOR[status]}22;border:1px solid {COLOR[status]};"
            f"color:{COLOR[status]}'>{'✔' if status == quality.GREEN else '✖'} {sentence}</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- the six dimensions
cards = quality.cards(checks, kept, lib, acc, runs, dbt_tests(), evidence, last_text)
for row in (cards[:3], cards[3:]):
    for col, card in zip(st.columns(3), row, strict=True):
        col.markdown(
            f"<div class='dq-card' style='--c:{COLOR[card.status]}'><h4>{card.dimension.capitalize()} "
            f"<span class='fr'>· {quality.FRENCH[card.dimension]}</span></h4>"
            f"<div class='q'>{quality.QUESTION[card.dimension]}</div><div class='n'>{card.number}</div>"
            f"<ul>{''.join(f'<li>{line}</li>' for line in card.lines)}</ul></div>", unsafe_allow_html=True)
    st.write("")
st.caption("Green: good. Orange: values our pipeline fixed, or close to the official reports. Red: a problem to fix "
           "before trusting the numbers. Grey: nothing measured yet.")

# ---------------------------------------------------------------- per match
st.subheader("Each match, each dimension")
names = {r.match_id: f"{r.home_team_short} {r.home_score}-{r.away_score} {r.away_team_short}" for r in lib.itertuples()}
grid = quality.grid(matches, checks, kept, acc, runs).melt("match_id", var_name="dimension", value_name="status")
grid["match"] = grid.match_id.map(names)
grid["meaning"] = grid.status.map(WORD)
grid["label"] = grid.dimension.map(lambda d: f"{d.capitalize()} · {quality.FRENCH[d]}")
order = [f"{d.capitalize()} · {quality.FRENCH[d]}" for d in quality.DIMENSIONS]
heat = alt.Chart(grid).mark_rect(cornerRadius=4, stroke="#0b1410", strokeWidth=3).encode(
    x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelColor=TEXT, labelAngle=0, labelLimit=0, orient="top",
                                                           labelOverlap=False, labelExpr="split(datum.value, ' · ')")),
    y=alt.Y("match:N", title=None, axis=alt.Axis(labelColor=TEXT, labelLimit=300)),
    color=alt.Color("status:N", scale=alt.Scale(domain=list(COLOR), range=list(COLOR.values())), legend=None),
    tooltip=["match:N", "label:N", "meaning:N"])
text = alt.Chart(grid).mark_text(color="#0b1410", fontWeight="bold").encode(
    x=alt.X("label:N", sort=order), y="match:N", text="meaning:N")
st.altair_chart((heat + text).properties(height=60 * len(matches)), width="stretch")
st.caption("Completeness judges our pipeline (what we kept), not the camera. Validity is orange when Silver had to put "
           "positions back on the pitch or remove impossible speeds: nothing wrong is left. Freshness: green when Gold "
           "was rebuilt within 10 minutes of the latest replay's final whistle, red when Gold is older than it.")

left, right = st.columns(2)
with left:
    st.markdown("**What the camera saw, every 5 minutes**")
    space = table("gold_space_control")
    cov = space[space.team_id == "HOME"].assign(match=lambda d: d.match_id.map(names),
                                               seen=lambda d: d.seconds_used / d.window_seconds)
    st.altair_chart(alt.Chart(cov).mark_line(point=True).encode(
        x=alt.X("window_index:O", title=None, axis=alt.Axis(labelExpr="''", ticks=False)),
        y=alt.Y("seen:Q", title="seen", scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(format="%", labelColor=TEXT, titleColor=TEXT)),
        color=alt.Color("match:N", legend=alt.Legend(orient="bottom", columns=1, labelColor=TEXT, title=None,
                                                      labelLimit=260)),
        tooltip=["match:N", alt.Tooltip("window_label:N", title="minutes"), alt.Tooltip("seen:Q", format=".0%")]
    ).properties(height=260), width="stretch")
    st.caption("Tracked seconds of each 5-minute window (0-5' ... 45+, 45-50' ... 90+), from left to right. The gaps are "
               "mostly dead-ball moments without a TV picture of the pitch: a limit of the source, shown, not judged.")
with right:
    st.markdown("**The last pipeline runs** (Dagster)")
    pr = pd.DataFrame([{"match": names.get(r.get("match_id"), r.get("match_id") or "all"),
                        "started": pd.to_datetime(r["started"], unit="s", utc=True), "result":
                        "passed" if r["status"] == "SUCCESS" else "failed", "trigger": r["trigger"],
                        "minutes": round((r["ended"] - r["started"]) / 60, 1) if r.get("ended") else None}
                       for r in runs if r.get("started")])
    if pr.empty:
        st.info("No Dagster run yet: `make dagster`, then replay a match.")
    else:
        st.altair_chart(alt.Chart(pr).mark_circle(size=220).encode(
            x=alt.X("started:T", title=None, axis=alt.Axis(labelColor=TEXT, format="%d %b %H:%M")),
            y=alt.Y("match:N", title=None, axis=alt.Axis(labelColor=TEXT, labelLimit=260)),
            color=alt.Color("result:N", scale=alt.Scale(domain=["passed", "failed"],
                                                         range=[COLOR[quality.GREEN], COLOR[quality.RED]]),
                            legend=alt.Legend(orient="bottom", labelColor=TEXT, title=None)),
            tooltip=["match:N", "started:T", "result:N", "trigger:N", "minutes:Q"]).properties(height=260),
            width="stretch")
        st.caption("Each dot is one run of the chain of a match: Bronze, Silver, Soda, Gold, Soda, report.")

# ---------------------------------------------------------------- what our checks stopped
st.subheader("Caught by our checks")
caught = quality.caught(runs, evidence)
if not caught:
    st.caption("No failed run yet.")
for c in caught:
    fix = f" Fixed in commit <code>{c['fix']}</code>." if c["fix"] else ""
    st.markdown(f"<div class='dq-caught'><b>{c['match_id'] or ''} · run {c['run']}</b> stopped at "
                f"<code>{c['stopped_at'] or '?'}</code>{' · not built: ' + c['not_built'] if c['not_built'] else ''}"
                f"<br>{c['what']}{fix}</div>", unsafe_allow_html=True)
if evidence:
    st.caption(f"Explanations and proofs from `make evidence`, {evidence['generated_at']}, commit {evidence['commit']}.")
else:
    st.caption("Run `make evidence` to add the explanations and the Live and Streaming proofs.")

# ---------------------------------------------------------------- details
with st.expander("Accuracy: our numbers against the official reports"):
    if acc.empty:
        st.info("docs/external_checks.yml is missing.")
    else:
        st.dataframe(acc.assign(match=acc.match_id.map(names), result=acc.status.map(
            {quality.GREEN: "same as a source", quality.ORANGE: "1 minute / 2 points away", quality.RED: "further"}))
            [["match", "what", "ours", "sources", "result"]], hide_index=True, width="stretch")
        st.caption(f"Sources and links: `docs/external_checks.yml`, checked {external['checked_on']}. A minute is exact "
                   "when at least one source gives it: the sources themselves disagree (Goodwin 62' or 63', Klein 50' "
                   "or 51').")

with st.expander(f"All {len(checks)} checks"):
    f1, f2, f3 = st.columns(3)
    dims = f1.multiselect("Dimension", sorted(checks.dimension.unique()))
    layers = f2.multiselect("Layer", sorted(checks.layer.unique()))
    res = f3.multiselect("Result", sorted(checks.result.unique()))
    shown = checks
    for col, chosen in (("dimension", dims), ("layer", layers), ("result", res)):
        if chosen:
            shown = shown[shown[col].isin(chosen)]
    st.dataframe(shown[["check", "dimension", "layer", "table", "result", "detail"]], hide_index=True, width="stretch",
                 height=420)
    st.caption("The dimension of each check: `soda/dimensions.yml` (a test makes sure no check is left without one).")
st.caption(CREDIT)
