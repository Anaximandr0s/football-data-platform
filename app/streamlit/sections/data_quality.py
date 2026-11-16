"""Data quality: result of the last Soda run on Silver and Gold (FOO-05). Written by `make soda`."""
import pandas as pd
import streamlit as st

import sitemap
from data import library, soda_results

sitemap.header("data_quality")

lib = library()
if lib is not None:
    st.subheader("Per match")
    st.dataframe(lib.assign(match=lib.home_team_short + " " + lib.home_score.astype(str) + "-" + lib.away_score.astype(str)
                            + " " + lib.away_team_short, tracked_pct=(lib.tracked_share * 100).round())
                 [["match_date", "match", "tracked_pct", "speeds_rejected"]],
                 hide_index=True, width="stretch",
                 column_config={"match_date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
                                "tracked_pct": st.column_config.ProgressColumn("Tracked", format="%d%%", min_value=0,
                                                                               max_value=100),
                                "speeds_rejected": st.column_config.NumberColumn(
                                    "Speeds rejected", help="Player-seconds above 40 km/h in bronze, set to null in Silver")})
    st.caption("Tracked: share of the two periods with player positions. Speeds rejected: player-seconds faster than "
               "40 km/h, a jump from a position SkillCorner estimated; Silver sets the speed to null and flags the row "
               "(speed_rejected), so it adds nothing to a distance.")

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
