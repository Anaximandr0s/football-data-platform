"""Live match (FOO-06): the match being replayed into Kafka (`make replay`), redrawn about once per second."""
import time

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import live
import live_feed
import viz
from data import CREDIT, mmss

st.set_page_config(page_title="Live match", page_icon="📡", layout="wide")
st.title("📡 Live match")

feed = live_feed.start_feed()
if feed is None:
    st.error("The live page reads Kafka: set KAFKA_BOOTSTRAP (kafka:9092 inside Docker, localhost:29092 outside).")
    st.stop()

STATUS_TEXT = {"gap": "No tracking: camera off the pitch",
               "stalled": "No data for a while: is the replay still running?",
               "waiting": "Waiting for the first positions of this replay"}


def colors_of(state: live.MatchState) -> dict[str, str]:
    teams = pd.DataFrame([{"match_id": state.match_id, "team_id": t, "team_color": state.info.get(f"{t.lower()}_color")}
                          for t in ("HOME", "AWAY")])
    return viz.team_colors(teams, state.match_id)


def possession_bar(state: live.MatchState, colors: dict[str, str]) -> None:
    share = live.possession_share(state)
    if share is None:
        st.caption("Possession: no second with a known owner yet.")
        return
    home, away, seconds = share
    owner = live.current_owner(state)
    st.markdown(
        f"<div style='display:flex;height:22px;border-radius:4px;overflow:hidden'>"
        f"<div style='width:{home:.0%};background:{colors['HOME']}'></div>"
        f"<div style='width:{away:.0%};background:{colors['AWAY']}'></div></div>",
        unsafe_allow_html=True)
    now = f" · now: {live.team_name(state, owner)}" if owner else " · now: ball dead or contested"
    st.caption(f"Possession {home:.0%} - {away:.0%} over {seconds // 60} min with a known owner{now}")


@st.fragment(run_every=1.0)
def live_view() -> None:
    states = {m: s for m, s in feed.snapshot().items() if s.info}
    if feed.error:
        st.warning(f"Kafka: {feed.error}")
    if not states:
        st.info("No replay seen yet. Start one: `make replay MATCH=m001 SPEED=5`.")
        return
    match = st.selectbox("Match", sorted(states), key="live_match",
                         format_func=lambda m: f"{m}: {states[m].info['home_team']} v {states[m].info['away_team']}")
    state = states[match]
    now_ms = int(time.time() * 1000)
    status, colors = live.status(state, now_ms), colors_of(state)
    home_goals, away_goals = live.score(state)
    clock = live.clock(state, now_ms)

    st.markdown(f"<h2 style='text-align:center;margin:0'>{state.info['home_team']} {home_goals} - {away_goals} "
                f"{state.info['away_team']}</h2>", unsafe_allow_html=True)
    period = "Full time" if status == "full_time" else f"Period {state.period}" if state.period else ""
    message = STATUS_TEXT.get(status)
    st.markdown(f"<p style='text-align:center;font-size:1.3rem'>{mmss(clock) if clock is not None else '--:--'}"
                f" · {period}{' · ' + message if message else ''}</p>", unsafe_allow_html=True)

    left, right = st.columns([3, 1])
    with left:
        frame = live.current_frame(state)
        ball = (state.ball[2], state.ball[3]) if state.ball else None
        fig = viz.live_pitch(frame[1] if frame else {}, state.players, ball, colors,
                             live.home_attacks_right(state), message=message)
        st.pyplot(fig, width="stretch")
        plt.close(fig)
        st.caption("As the camera sees it: teams switch ends at half-time (arrows: direction of attack). "
                   "Lighter dots are positions estimated by SkillCorner, not seen by the camera.")
    with right:
        possession_bar(state, colors)
        st.markdown("**Last event**")
        st.write(live.event_line(state) or "Nothing yet")
        st.markdown("**Team shape now** (outfield players)")
        shape = live.team_shape(state, frame[1]) if frame and status == "live" else {}
        if shape:
            st.dataframe(pd.DataFrame([{"team": live.team_name(state, t), "width (m)": w, "length (m)": ln}
                                       for t, (w, ln) in shape.items()]), hide_index=True)
        else:
            st.caption("Shown while positions arrive.")
        with st.container(border=True):
            st.markdown("**Last 5 minutes**")
            st.caption("Possession, distance per minute, top speed and pressing per 5 minutes: computed by the "
                       "streaming job (FOO-08, topic foot-live-stats), not built yet.")
    st.caption(f"{feed.messages:,} Kafka messages read. {CREDIT}")


live_view()
