"""Data quality: result of the last Soda run on Silver and Gold (FOO-05). Written by `make soda`."""
import pandas as pd
import streamlit as st

from data import soda_results

st.set_page_config(page_title="Data quality", page_icon="✅", layout="wide")
st.title("✅ Data quality")
st.markdown("Soda checks run on the Silver and Gold layers (`make soda`). This page shows the **last run**.")

results = soda_results()
if not results:
    st.info("No Soda result yet: run `make soda` (it writes `data/soda/silver.json` and `data/soda/gold.json`).")
    st.stop()

ICON = {"pass": "✅ pass", "fail": "❌ fail", "warn": "⚠️ warn"}

for layer in ("silver", "gold"):
    if layer not in results:
        st.warning(f"No result for {layer}: run `make soda-{layer}`.")
        continue
    r = results[layer]
    st.subheader(layer.capitalize())
    c = st.columns(4)
    c[0].metric("Passed", r["passed"])
    c[1].metric("Failed", r["failed"], delta=None if not r["failed"] else "needs attention", delta_color="inverse")
    c[2].metric("Warnings", r["warned"])
    c[3].metric("Errors", r["errors"])
    st.caption(f"Last run: {r['finished_at_utc']} (UTC)")
    checks = pd.DataFrame(r["checks"])
    only_bad = st.checkbox("Show only checks that did not pass", value=bool(r["failed"] or r["errors"]), key=f"bad_{layer}")
    if only_bad:
        checks = checks[checks.outcome != "pass"]
    checks = checks.assign(result=checks.outcome.map(lambda o: ICON.get(o, o)))
    if "detail" not in checks:                       # a result file written before the explanations existed
        checks["detail"] = ""
    st.dataframe(checks[["result", "table", "name", "detail"]], hide_index=True, width="stretch")
    if r["failed"]:
        st.caption("`detail` says why a check failed: how many rows break the rule and the first ones, or the column whose "
                   "type or presence differs from the contract. A result older than the data (a table rebuilt since) "
                   "stays red until `make soda` runs again.")
