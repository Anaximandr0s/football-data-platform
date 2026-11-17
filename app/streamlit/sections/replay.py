"""Replay (MATCHES: R1, S1): a stored match played on the MatchLens pitch, with a panel that knows only what happened up
to the second being watched. The whole match goes to the browser once (pitch.js plays it); Python fills the panel when
the browser reports the replay time (pause, scrub, goal jump, click, and every 2 s while playing)."""
import duckdb
import pandas as pd
import streamlit as st

import charts
import clock
import pitch
import playerstats
import replayer
import sitemap
import viz
from data import CREDIT, current_match, library, replay_frames, require_gold, source_key, table

sitemap.header("replay")
teams = require_gold()
match = current_match(teams)
lib = library()
if lib is None or match not in set(lib.match_id):
    st.info("The match library is not built yet: run `make gold`.")
    st.stop()
info = lib[lib.match_id == match].iloc[0]
bounds = (int(info.p1_start_ts), int(info.p2_start_ts))
colors = viz.team_colors(teams, match)
names = {"HOME": info.home_team_short, "AWAY": info.away_team_short}


@st.cache_data(show_spinner="Loading the match...", max_entries=2)
def match_data(match_id: str, source: str) -> tuple[pd.DataFrame, dict]:
    frames = replay_frames(match_id)
    return frames, replayer.payload(frames, f"{match_id}|{source}")


try:
    frames, payload = match_data(match, source_key())
except duckdb.Error as exc:            # a Gold file built before gold_replay_frames: say what to run
    st.error("This Gold file has no replay frames yet: run `make gold`.")
    st.caption(str(exc)[:300])
    st.stop()
if frames.empty:
    st.info("No tracked second for this match in Gold.")
    st.stop()

roster = frames[frames.object_type == "player"].drop_duplicates("object_id").set_index("object_id")
cards = table("gold_player_card")
short = dict(zip(cards[cards.match_id == match].player_id, cards[cards.match_id == match].short_name, strict=False))
players = {pid: [r.team_id, int(r.shirt_number), short.get(pid, pid), r.position == "GK"] for pid, r in roster.iterrows()}
events = table("gold_events")
events = events[events.match_id == match]
goals = replayer.goals(events, *bounds)
first, last = payload["t"][0], int(info.p2_end_ts)
controls = {"start": first, "end": last, "goals": goals, "names": [names["HOME"], names["AWAY"]],
            "shots": replayer.shots(events, *bounds), "events": replayer.key_events(events, names, *bounds),
            "clock": replayer.clock_labels(first, last, *bounds)}
timeline = table("gold_match_timeline")
timeline = timeline[timeline.match_id == match]
space = table("gold_space_control")
space = space[(space.match_id == match) & (space.team_id == "HOME")]


def player_panel(player_id: str, ts: int) -> None:
    team, shirt, name, _ = players[player_id]
    stats = replayer.player_until(frames, player_id, ts)
    top = "not yet" if stats.top_speed_kmh is None else f"about {stats.top_speed_kmh:.0f} km/h"
    st.markdown(f"<div class='ml-kicker'>SELECTED PLAYER</div>"
                f"<h3 style='margin:.1rem 0 .4rem 0'>#{shirt} {name}</h3>"
                f"<div class='ml-meta'>{names[team]} · up to {clock.running(ts, None, *bounds)}</div>"
                "<div class='ml-stats'>"
                f"<div><span>Distance</span><b>{stats.distance_m / 1000:.2f} km</b></div>"
                f"<div><span>Top speed</span><b>{top}</b></div>"
                f"<div><span>Sprints</span><b>{stats.sprint_count}</b></div></div>", unsafe_allow_html=True)
    pitch.show(key="replay_heat", players={}, colors=colors, clickable=False, arrows={"home": "right"},
               heat={"nx": playerstats.ZONES_X, "ny": playerstats.ZONES_Y, "cells": playerstats.heat_cells(stats.zones),
                     "color": colors[team]})
    st.caption(f"{stats.tracked_seconds / 60:.0f} tracked minutes so far; the formulas of Live and Gold.")
    st.button("Close", key="replay_close", on_click=lambda: st.session_state.pop("replay_player", None))


def panel(ts: int) -> None:
    home, away = replayer.score_at(goals, ts)
    st.markdown(f"<div class='ml-kicker'>AT {clock.running(ts, None, *bounds)}</div>"
                f"<h3 style='margin:.1rem 0 .6rem 0'>{names['HOME']} {home} - {away} {names['AWAY']}</h3>",
                unsafe_allow_html=True)
    selected = st.session_state.get("replay_player", {}).get(match)
    if selected in players:
        player_panel(selected, ts)
        st.divider()
    h, a = replayer.possession_until(frames, ts)
    if h + a:
        st.markdown(viz.possession_bar(h / (h + a), colors, names), unsafe_allow_html=True)
        st.caption(f"Possession so far {h / (h + a):.0%} - {a / (h + a):.0%} over {(h + a) // 60} min with a known owner")
    share = replayer.space_now(frames, ts)
    if share is not None:
        st.caption(f"Space control now: {names['HOME']} {share:.0%}, {names['AWAY']} {1 - share:.0%} of the pitch (S1)")
    done = replayer.windows_until(timeline, ts).head(4)
    st.markdown("**Every 5 minutes** (Gold)")
    if done.empty:
        st.caption("The first 5-minute window is not over yet.")
    else:
        st.dataframe(pd.DataFrame({
            "minutes": [f"{w}'" for w in done.window_label],
            "possession": ["-" if g else f"{h_:.0%} - {a_:.0%}" for g, h_, a_ in
                           zip(done.possession_greyed, done.home_possession, done.away_possession, strict=True)],
            "passes": [f"{int(h_)} - {int(a_)}" for h_, a_ in zip(done.home_passes, done.away_passes, strict=True)],
            "xThreat": [f"{h_:.2f} - {a_:.2f}" for h_, a_ in zip(done.home_xthreat, done.away_xthreat, strict=True)]}),
            hide_index=True, width="stretch")
        st.caption("Only windows already over: a window being played would show Gold values from its future.")


@st.fragment
def replay_view() -> None:
    sent = st.session_state.get("replay_sent")
    full = sent != payload["key"]
    left, right = st.columns([3, 1])
    with left:
        selected = st.session_state.get("replay_player", {}).get(match)
        result = pitch.replay(key=f"replay_{match}", players=players, colors=colors, replay=controls, names=names,
                              frames=payload if full else {"key": payload["key"]}, selected=selected)
        if full:
            st.session_state["replay_sent"] = payload["key"]
        elif result.reload == payload["key"]:         # the browser lost its copy (remount): send the match again
            st.session_state["replay_sent"] = None
            st.rerun(scope="fragment")
        pick = result.pick                            # {player, n}: a click counts once, even after "Close"
        if pick and pick.get("n") != st.session_state.get("replay_pick"):
            st.session_state["replay_pick"] = pick["n"]
            st.session_state["replay_player"] = {**st.session_state.get("replay_player", {}), match: pick["player"]}
        st.caption(f"{names['HOME']} attacks to the right in both halves. Positions are 1 per second (Gold, 1 Hz): "
                   "Smooth movement draws the straight line between two consecutive seconds at the screen's frame "
                   "rate, never across a camera gap; switch it off to see the raw 1 Hz jumps. Lighter dots are "
                   "positions estimated by SkillCorner. Click a player for his stats up to now.")
    ts = int(result.time) if result.time is not None else first
    with right:
        panel(ts)
    st.markdown("**Space control** (S1, mean per 5 minutes; the gold line is now)")
    st.altair_chart(charts.finish(charts.space_control(space, colors["HOME"], names["HOME"], last / 60,
                                                       clock.axis_ticks(*bounds, end_ts=last), bounds[1] / 60,
                                                       ts / 60)), width="stretch")


replay_view()
st.caption("Our own viewer, inspired by SkillCorner's Tracking Viewer: the code and the design are MatchLens'. " + CREDIT)
