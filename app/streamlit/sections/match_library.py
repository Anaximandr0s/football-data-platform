"""Match library (MATCHES): every stored match, newest first, with a Choose button: the chosen match follows the visitor
on every page. Team names are the ones fans use (gold_match_library.home_team_short, from the dbt seed team_names)."""

import streamlit as st

import glossary
import sitemap
from data import CREDIT, library, require_gold

sitemap.header("match_library")
require_gold()
lib = library()
if lib is None:
    st.info("The match library is not built yet: run `make gold` (it adds the table gold_match_library).")
    st.stop()


def choose(match_id: str) -> None:
    st.session_state["match_id"] = match_id


current = st.session_state.get("match_id")
c = st.columns(3)
c[0].metric("Matches", len(lib))
c[1].metric("Teams", len(set(lib.home_team_short) | set(lib.away_team_short)))
c[2].metric("Tracked, on average", f"{lib.tracked_share.mean():.0%}", help=glossary.help("tracked"))

for row in lib.itertuples():
    chosen = row.match_id == current
    with st.container(border=True):
        date, match, where, button = st.columns([1.3, 3.2, 2.2, 1.3], vertical_alignment="center")
        date.markdown(
            f"**{row.match_date:%d %b %Y}**<div class='ml-meta'>{row.competition} · {row.round}</div>",
            unsafe_allow_html=True,
        )
        match.markdown(
            f"<div class='ml-board'><div class='team'>{row.home_team_short}</div>"
            f"<div class='score'>{row.home_score} - {row.away_score}</div>"
            f"<div class='team away'>{row.away_team_short}</div></div>",
            unsafe_allow_html=True,
        )
        where.markdown(
            f"<div class='ml-meta'>{row.stadium}<br>{glossary.term('tracked', 'Tracked')}: "
            f"{row.tracked_share:.0%} of the match</div>",
            unsafe_allow_html=True,
        )
        button.button(
            "Chosen" if chosen else "Choose",
            key=f"lib_{row.match_id}",
            on_click=choose,
            args=(row.match_id,),
            type="primary" if chosen else "secondary",
            disabled=chosen,
            icon=":material/check:" if chosen else None,
            width="stretch",
        )
if current in set(lib.match_id):
    row = lib[lib.match_id == current].iloc[0]
    st.success(
        f"Current match: {row.home_team_short} {row.home_score} - {row.away_score} {row.away_team_short} "
        f"({row.match_date:%d %B %Y}). Every page shows this match."
    )
    st.page_link(
        "sections/replay.py", label=f"Replay {row.home_team_short} - {row.away_team_short}", icon=":material/replay:"
    )
st.caption(
    "Tracked = share of the two halves with player positions: the camera loses the play mostly when the ball is "
    "dead. " + CREDIT
)
