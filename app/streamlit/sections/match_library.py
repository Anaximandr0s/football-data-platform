"""Match library (MATCHES): every stored match, newest first. Selecting a row makes it the match of every page."""
import streamlit as st

import sitemap
from data import CREDIT, library, require_gold

sitemap.header("match_library")
require_gold()
lib = library()
if lib is None:
    st.info("The match library is not built yet: run `make gold` (it adds the table gold_match_library).")
    st.stop()


def select_match() -> None:
    rows = st.session_state["library_table"].selection.rows
    if rows:
        st.session_state["match_id"] = shown.iloc[rows[0]].match_id


shown = lib.assign(score=lib.home_score.astype(str) + " - " + lib.away_score.astype(str),
                   tracked_pct=(lib.tracked_share * 100).round()).reset_index(drop=True)
current = st.session_state.get("match_id")
c = st.columns(3)
c[0].metric("Matches", len(lib))
c[1].metric("Teams", len(set(lib.home_team) | set(lib.away_team)))
c[2].metric("Tracked, on average", f"{lib.tracked_share.mean():.0%}")

st.dataframe(
    shown[["match_date", "competition", "round", "home_team", "score", "away_team", "stadium", "tracked_pct"]],
    key="library_table", on_select=select_match, selection_mode="single-row", hide_index=True, width="stretch",
    column_config={
        "match_date": st.column_config.DateColumn("Date", format="D MMM YYYY"),
        "competition": "Competition", "round": "Round", "home_team": "Home", "score": "Score", "away_team": "Away",
        "stadium": "Stadium",
        "tracked_pct": st.column_config.ProgressColumn("Tracked", help="Share of the match the camera tracked",
                                                       format="%d%%", min_value=0, max_value=100),
    })
if current in set(lib.match_id):
    row = lib[lib.match_id == current].iloc[0]
    st.success(f"Current match: {row.home_team} {row.home_score} - {row.away_score} {row.away_team} "
               f"({row.match_date:%d %B %Y}). Select a row to change it; every page follows.")
    st.page_link("sections/replay.py", label=f"Replay {row.home_team_short} - {row.away_team_short}",
                 icon=":material/replay:")
st.caption("Tracked = share of the two periods with player positions: the camera loses the play mostly when the ball is "
           "dead. " + CREDIT)
