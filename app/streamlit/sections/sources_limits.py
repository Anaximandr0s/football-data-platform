"""Sources & limits (BEHIND THE DATA): where the data comes from, what it cannot tell, and how it was checked against
official match reports. The text comes from docs/data-sources.md and docs/requirements-coverage.md, so the page and the
report never disagree."""
import streamlit as st

import sitemap
from data import CREDIT, doc_section, library

sitemap.header("sources_limits")

lib = library()
c = st.columns(4)
c[0].metric("Source", "SkillCorner")
c[1].metric("Matches stored", len(lib) if lib is not None else "-")
c[2].metric("Positions per player", "1 per second")
c[3].metric("Seconds tracked", f"{lib.tracked_share.mean():.0%}" if lib is not None else "-",
            help="Mean over the stored matches: the rest are camera gaps, mostly dead-ball stoppages")
st.markdown("Real broadcast-tracking data of A-League matches, season 2024/2025, published by SkillCorner as open data "
            "(MIT licence). Positions come from the TV picture: a player off screen is **estimated** by SkillCorner, "
            "and a second with no picture of the pitch has no data at all. There is no expected-goals model and no "
            "corner event in this source.")

if lib is not None:
    st.dataframe(lib.assign(match=lib.home_team_short + " " + lib.home_score.astype(str) + "-"
                            + lib.away_score.astype(str) + " " + lib.away_team_short)
                 [["match_date", "match", "competition", "round", "stadium", "tracked_share"]],
                 hide_index=True, width="stretch",
                 column_config={"match_date": st.column_config.DateColumn("date", format="D MMM YYYY"),
                                "tracked_share": st.column_config.ProgressColumn("tracked", format="percent",
                                                                                 min_value=0, max_value=1)})

st.subheader("What the data cannot tell")
st.markdown(doc_section("data-sources.md", "Known limits (state them in the report)"))

st.subheader("Checked against official sources")
st.markdown("Goal minutes and possession of every stored match, compared with the clubs' match reports, news agencies "
            "and FBref.")
st.markdown(doc_section("requirements-coverage.md", "External check against official sources"))
st.caption(CREDIT)
