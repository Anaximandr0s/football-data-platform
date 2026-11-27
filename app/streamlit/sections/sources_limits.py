"""Sources & limits (BEHIND THE DATA): where the data comes from, what it cannot tell, and how it was checked against
official match reports, in words for any visitor. The same facts, with their technical detail, are in
docs/data-sources.md (limits) and docs/external_checks.yml (official sources)."""

import streamlit as st

import glossary
import quality
import sitemap
from data import CREDIT, external_checks, library, table

sitemap.header("sources_limits")

lib = library()
c = st.columns(4)
c[0].metric("Source", "SkillCorner")
c[1].metric("Matches stored", len(lib) if lib is not None else "-")
c[2].metric("Positions per player", "1 per second")
c[3].metric(
    "Match time seen",
    f"{lib.tracked_share.mean():.0%}" if lib is not None else "-",
    help=glossary.help("tracked") + " Mean over the stored matches.",
)
st.markdown(
    "Real broadcast-tracking data of A-League matches, season 2024/2025, published by SkillCorner as open data "
    "(MIT licence). Positions come from the TV picture: a player off screen is **estimated** by SkillCorner, "
    "and a second with no picture of the pitch has no data at all. There is no expected-goals model and no "
    "corner event in this source."
)

if lib is not None:
    st.dataframe(
        lib.assign(
            match=lib.home_team_short
            + " "
            + lib.home_score.astype(str)
            + "-"
            + lib.away_score.astype(str)
            + " "
            + lib.away_team_short
        )[["match_date", "match", "competition", "round", "stadium", "tracked_share"]],
        hide_index=True,
        width="stretch",
        column_config={
            "match_date": st.column_config.DateColumn("date", format="D MMM YYYY"),
            "tracked_share": st.column_config.ProgressColumn("tracked", format="percent", min_value=0, max_value=1),
        },
    )

st.subheader("What the data cannot tell")
st.markdown(
    f"""
- **The camera does not see everything.** About three quarters of each match is {glossary.term("tracked")}; the rest is
  mostly replays and close-ups while the ball is out of play. In those seconds there are no positions at all, and the
  Live and Replay pitches say "camera off the pitch".
- **Distances and speeds are approximate.** They count only the seconds the camera saw, from one position per second:
  they are lower than what a GPS vest would measure. Compare players inside one match rather than quoting them.
- **Some positions are estimated.** When a player is off the TV picture, SkillCorner estimates where he is; these dots
  are lighter on the pitch. A speed above 40 km/h is impossible and is removed.
- **A match lasts about 100 minutes**, stoppage time included: the clock shows 45+ and 90+ like on TV.
- **No expected goals (xG) and no corners.** The source has neither; {glossary.term("xThreat")} measures the danger of
  passes, not of shots.
- **Both halves are drawn the same way.** The home team always attacks to the right on our pitches, also after
  half-time, while on TV the teams switch ends.
""",
    unsafe_allow_html=True,
)

st.subheader("Checked against official sources")
st.markdown(
    "Goal minutes and possession of every stored match, compared with the clubs' match reports, news agencies "
    "and FBref."
)
external = external_checks()
if external is None or lib is None:
    st.info("docs/external_checks.yml or the Gold match library is missing.")
else:
    acc = quality.accuracy(external, table("gold_events"), lib, table("gold_team_profile"))
    names = {
        r.match_id: f"{r.home_team_short} {r.home_score}-{r.away_score} {r.away_team_short}" for r in lib.itertuples()
    }
    st.dataframe(
        acc.assign(
            match=acc.match_id.map(names),
            agrees=acc.status.map(
                {quality.GREEN: "yes, as a source", quality.ORANGE: "1 minute / 2 points away", quality.RED: "no"}
            ),
        )[["match", "what", "ours", "sources", "agrees"]],
        hide_index=True,
        width="stretch",
    )
    links = " · ".join(f"[{s['name']} ({k.split('_')[-1]})]({s['url']})" for k, s in external["sources"].items())
    st.caption(f"Checked {external['checked_on']}. Sources: {links}")
st.caption(CREDIT)
