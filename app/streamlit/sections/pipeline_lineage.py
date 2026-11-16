"""Pipeline & lineage (BEHIND THE DATA): the Dagster asset graph coloured by one run, the latest runs, and the dbt
lineage of a Gold table. Reads data/pipeline/*.json (written by Dagster after each run) and dbt/target/manifest.json."""
import os

import streamlit as st

import lineage
import sitemap
from data import dbt_manifest, pipeline_file

DAGSTER_URL = f"http://localhost:{os.getenv('DAGSTER_PORT', '3000')}"

sitemap.header("pipeline_lineage")
st.markdown("A replay that reaches its last second starts the chain of its match in Dagster: Bronze is checked, Spark "
            "builds Silver, **Soda checks Silver**, dbt builds Gold, **Soda checks Gold**, and a post-match report is "
            "written. A failed check stops everything after it, so a damaged table never reaches this site.")

graph, runs = pipeline_file("graph"), pipeline_file("runs") or []
if graph is None:
    st.info(f"No Dagster run yet: `make dagster`, then replay a match (`make replay MATCH=m001`) or start a run in "
            f"[Dagster]({DAGSTER_URL}).")
else:
    st.subheader("The asset graph")
    pipeline = [r for r in runs if r["job"] == "match_pipeline"]
    labels = {r["run_id"]: f"{r['match_id']} · {'success' if r['status'] == 'SUCCESS' else 'failed'} · {r['trigger']}"
              for r in pipeline}
    chosen = st.selectbox("Colour the graph with the run", list(labels), format_func=labels.get) if labels else None
    run = next((r for r in pipeline if r["run_id"] == chosen), None)
    st.graphviz_chart(lineage.pipeline_dot(graph, run), width="stretch")
    st.markdown(" ".join(f"<span class='ml-chip' style='background:{c};padding:2px 8px;border-radius:4px;"
                         f"margin-right:6px'>{s}</span>" for s, c in lineage.STATE_COLOR.items()),
                unsafe_allow_html=True)
    st.caption("✓ soda_silver, soda_gold: the blocking Soda checks. The dbt models are one step (`gold`, one `dbt "
               "build`); the dbt tests run inside it. Gold is rebuilt whole for every match: one DuckDB file holds "
               f"them all. Open the live graph in [Dagster]({DAGSTER_URL}).")

    st.subheader("Latest runs")
    table = lineage.runs_table(runs)
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={"started": st.column_config.DatetimeColumn("started (UTC)", format="D MMM, HH:mm:ss")})
    st.caption("trigger: sensor = the end of a replay, schedule = the nightly Soda run (03:00 UTC), manual = from the "
               "Dagster UI. not built: steps skipped because a check or step before them failed.")

st.subheader("Where a Gold table comes from")
manifest = dbt_manifest()
if manifest is None:
    st.info("No dbt manifest yet: `make gold` writes `dbt/target/manifest.json`.")
    st.stop()
gold = sorted(v["name"] for v in manifest["nodes"].values()
              if v["resource_type"] == "model" and v["name"].startswith("gold_"))
model = st.selectbox("Gold table", gold, index=gold.index("gold_player_match_stats") if "gold_player_match_stats" in gold
                     else 0)
node = next(v for v in manifest["nodes"].values() if v["resource_type"] == "model" and v["name"] == model)
graph_col, info_col = st.columns([1, 1])
with graph_col:     # the chart fills its column: a half-width column keeps a small lineage readable
    st.graphviz_chart(lineage.dbt_dot(manifest, model), width="stretch")
with info_col:
    st.markdown(f"**{model}**: {node.get('description') or 'no description'}")
    columns = node.get("columns") or {}
    if columns:
        st.dataframe([{"column": c, "meaning": v.get("description", "")} for c, v in columns.items()],
                     hide_index=True, width="stretch", height=320)
st.caption(f"From the dbt manifest: `dbt/models/{node['path']}` and every model it reads, back to the Silver tables. "
           "The code of each box is in `dbt/models/`.")
