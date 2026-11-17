"""Pipeline & lineage (BEHIND THE DATA): the Dagster asset graph coloured by one run, the latest runs, and the dbt
lineage of a Gold table. Reads data/pipeline/*.json (written by Dagster after each run) and dbt/target/manifest.json."""
import os

import duckdb
import streamlit as st

import lineage
import sitemap
from data import dbt_manifest, doc_text, pipeline_file, table

DAGSTER_URL = f"http://localhost:{os.getenv('DAGSTER_PORT', '3000')}"

sitemap.header("pipeline_lineage")
st.markdown("A match reaches this site along two paths. **After the match**, its data is copied, cleaned, checked, "
            "turned into statistics and checked again; a failed check stops everything after it, so a damaged table "
            "never reaches the site. **During the match**, the Live page reads the same messages directly, and Spark "
            "adds statistics every 5 minutes.")
st.graphviz_chart(lineage.overview_dot(), width="stretch")
st.caption("Kafka carries the match second by second. Soda checks Silver and Gold (green) before anyone sees them; "
           "Spark Streaming adds statistics every 5 minutes during the match. Yellow: what visitors see.")

graph, runs = pipeline_file("graph"), pipeline_file("runs") or []
if st.toggle("Show details: every table, step and run", key="pl_details"):
    if graph is None:
        st.info(f"No Dagster run yet: `make dagster`, then replay a match (`make replay MATCH=m001`) or start a run in "
                f"[Dagster]({DAGSTER_URL}).")
    else:
        st.subheader("The asset graph")
        pipeline = [r for r in runs if r["job"] == "match_pipeline"]
        labels = {r["run_id"]: f"{r['match_id']} · {'success' if r['status'] == 'SUCCESS' else 'failed'} · "
                               f"{r['trigger']}" for r in pipeline}
        chosen = st.selectbox("Colour the graph with the run", list(labels), format_func=labels.get) if labels else None
        run = next((r for r in pipeline if r["run_id"] == chosen), None)
        st.graphviz_chart(lineage.pipeline_dot(graph, run), width="stretch")
        st.markdown(" ".join(f"<span class='ml-key'><i style='background:{c};border:1px solid #8a948f'></i>{s}</span>"
                             for s, c in lineage.STATE_COLOR.items()), unsafe_allow_html=True)
        st.caption("✓ soda_silver, soda_gold: the blocking Soda checks. The dbt models are one step (`gold`, one `dbt "
                   "build`); the dbt tests run inside it. Gold is rebuilt whole for every match: one DuckDB file holds "
                   f"them all. Open the live graph in [Dagster]({DAGSTER_URL}).")
        st.subheader("Latest runs")
        st.dataframe(lineage.runs_table(runs), hide_index=True, width="stretch",
                     column_config={"started": st.column_config.DatetimeColumn("started (UTC)",
                                                                              format="D MMM, HH:mm:ss")})
        st.caption("trigger: sensor = the end of a replay, schedule = the nightly Soda run (03:00 UTC), manual = from "
                   "the Dagster UI. not built: steps skipped because a check or step before them failed.")

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
    documented = {c: v.get("description", "") for c, v in (node.get("columns") or {}).items()}
    contract = lineage.contract_meanings(doc_text("contrat_donnees.md"), model)
    try:
        names = list(table(model).columns)
    except (ValueError, duckdb.Error):          # a model the app does not read: its documented columns only
        names = list(documented)
    st.dataframe([{"column": c, "meaning": documented.get(c) or contract.get(c) or "–"} for c in names],
                 hide_index=True, width="stretch", height=360)
st.caption(f"From the dbt manifest: `dbt/models/{node['path']}` and every model it reads, back to the Silver tables. "
           "The meaning of each column comes from the data contract (`docs/contrat_donnees.md`, section 10).")
