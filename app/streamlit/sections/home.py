"""Home: the MatchLens door. Choose a match from the library, then say who you are; the menu then shows that view."""

import time

import streamlit as st

import live
import live_feed
import sitemap
import theme
from data import CREDIT, fan_names, library, require_gold

PERSONAS = {
    "fan": (
        "I am a Fan",
        ":material/stadium:",
        "What happened, who played well and why we won or lost, in plain words and player cards.",
    ),
    "coach": (
        "I am a Coach",
        ":material/sports:",
        "Shape, pressing, build-up and fatigue of a team, with every number explained and its limits stated.",
    ),
}


def choose_match(match_id: str) -> None:
    st.session_state["match_id"] = match_id


def choose_view(view: str) -> None:
    st.session_state["view"] = view
    st.session_state["go_to"] = sitemap.FIRST_PAGE[view]


st.image(theme.LOGO, width=380)
st.markdown(
    "<div class='ml-tagline'>Tracking data, explained: for the fan in the stands and the coach on the bench.</div>",
    unsafe_allow_html=True,
)

feed = live_feed.start_feed()  # None without Kafka: then there is nothing live to announce
if feed is not None:
    states = feed.snapshot()
    playing = live.now_playing(states, int(time.time() * 1000))
    if playing:
        m = playing[0]
        teams = " v ".join(live.team_name(states[m], t, fan_names(m)) for t in ("HOME", "AWAY"))
        with st.container(border=True):
            left, right = st.columns([4, 1], vertical_alignment="center")
            left.markdown(
                f"<span class='ml-badge'>Live now</span> &nbsp;**{teams}** is being played right now.",
                unsafe_allow_html=True,
            )
            right.page_link("sections/live_match.py", label="Watch", icon=":material/play_circle:")

require_gold()
lib = library()
chosen = st.session_state.get("match_id")

st.subheader("1. Choose a match")
if lib is None:
    st.info("The match library is not built yet: run `make gold`. Pick the match in the sidebar meanwhile.")
else:
    for start in range(0, len(lib), 3):
        for col, row in zip(st.columns(3), lib.iloc[start : start + 3].itertuples(), strict=False):
            with col.container(border=True):
                st.markdown(
                    f"<div class='ml-meta'>{row.competition} · {row.round} · {row.match_date:%d %b %Y}</div>"
                    f"<div class='ml-board'><div class='team'>{row.home_team_short}</div>"
                    f"<div class='score'>{row.home_score} - {row.away_score}</div>"
                    f"<div class='team away'>{row.away_team_short}</div></div>"
                    f"<div class='ml-meta'>{row.stadium} · {row.tracked_share:.0%} of the match tracked</div>",
                    unsafe_allow_html=True,
                )
                selected = row.match_id == chosen
                st.button(
                    "Selected" if selected else "Choose this match",
                    key=f"pick_{row.match_id}",
                    type="primary" if selected else "secondary",
                    disabled=selected,
                    width="stretch",
                    on_click=choose_match,
                    args=(row.match_id,),
                )

st.subheader("2. Who are you?")
for col, (view, (title, icon, text)) in zip(st.columns(2), PERSONAS.items(), strict=True):
    with col.container(border=True):
        st.markdown(f"<div class='ml-card-inner'><h3>{title}</h3><p>{text}</p></div>", unsafe_allow_html=True)
        st.button(
            f"Open the {view} view",
            key=f"view_{view}",
            icon=icon,
            type="primary",
            width="stretch",
            on_click=choose_view,
            args=(view,),
        )

st.caption("LIVE, MATCHES and BEHIND THE DATA are open to both. " + CREDIT)
