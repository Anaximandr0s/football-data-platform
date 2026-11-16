"""Live match (FOO-06): the match being replayed into Kafka (`make replay`), redrawn about once per second.
A click on a player shows his stats so far, with the formulas of Gold (playerstats.py)."""
import time

import pandas as pd
import streamlit as st

import cards
import clock
import live
import live_feed
import pitch
import playerstats
import sitemap
import viz
from data import CREDIT, fan_names

sitemap.header("live_match")

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


def player_panel(state: live.MatchState, player_id: str, colors: dict[str, str], names: dict | None) -> None:
    """Stats so far of the clicked player: distance, top speed, sprints and his heatmap."""
    info = state.players.get(player_id, {})
    team = info.get("team_id", "HOME")
    stats = live.player_stats(state, player_id)
    st.markdown(f"<div class='ml-kicker'>SELECTED PLAYER</div>"
                f"<h3 style='margin:.1rem 0 .4rem 0'>#{info.get('shirt_number', '')} {info.get('short_name', player_id)}</h3>"
                f"<div class='ml-meta'>{live.team_name(state, team, names)} · {info.get('position', '')}</div>",
                unsafe_allow_html=True)
    top = "not yet" if stats.top_speed_kmh is None else f"about {stats.top_speed_kmh:.0f} km/h"
    st.markdown("<div class='ml-stats'>"
                f"<div><span>Distance</span><b>{stats.distance_m / 1000:.2f} km</b></div>"
                f"<div><span>Top speed</span><b>{top}</b></div>"
                f"<div><span>Sprints</span><b>{stats.sprint_count}</b></div></div>", unsafe_allow_html=True)
    pitch.show(key="live_heat", players={}, colors=colors, clickable=False,
               heat={"nx": 6, "ny": 4, "cells": playerstats.heat_cells(stats.zones), "color": colors[team]},
               arrows={"home": "right"})
    st.caption(f"So far: {stats.tracked_seconds / 60:.0f} tracked minutes. Heatmap with HOME attacking to the right; "
               "top speed counts only speeds whose two positions the camera saw.")
    st.button("Close", key="live_close", on_click=lambda: st.session_state.pop("live_player", None))


def five_minutes(state: live.MatchState, stats: list[dict], names: dict | None) -> None:
    """The 5-minute windows of this replay from the streaming job (foot-live-stats), newest first."""
    st.markdown("**Every 5 minutes** (Spark streaming)")
    teams = sorted((r for r in stats if r.get("kind") == "team"), key=lambda r: (-r["window_index"], r["team_id"]))
    if not teams:
        st.caption("No window yet. The streaming job must run before the replay starts: `make streaming`.")
        return
    home, away = live.team_name(state, "HOME", names), live.team_name(state, "AWAY", names)
    windows = {}
    for r in teams:
        windows.setdefault(r["window_index"], {})[r["team_id"]] = r
    table = []
    for pair in list(windows.values())[:4]:
        h, a = pair.get("HOME", {}), pair.get("AWAY", {})
        poss = "-" if h.get("possession_greyed", True) else f"{h['possession_share']:.0%} - {a['possession_share']:.0%}"
        press = ["-" if r.get("ppp_greyed", True) else f"{r['ppp']:.2f}" for r in (h, a)]
        table.append({"minutes": f"{h.get('window_label', a.get('window_label'))}'",
                      "status": "complete" if h.get("complete") else "in progress",
                      f"possession {home} - {away}": poss, f"{home} pressing per opp. pass": press[0],
                      f"{away} pressing per opp. pass": press[1]})
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    latest = max(windows)
    players = [r for r in stats if r.get("kind") == "player" and r["window_index"] == latest and r["tracked_seconds"]]
    best = sorted(players, key=lambda r: -r["distance_m"] / (r["tracked_seconds"] / 60))[:3]
    if best:
        label = next(iter(windows[latest].values()))["window_label"]
        st.caption(f"Most ground covered in {label}': " + ", ".join(
            f"{state.players.get(r['player_id'], {}).get('short_name', r['player_id'])} "
            f"{r['distance_m'] / (r['tracked_seconds'] / 60):.0f} m/min (top {r['max_speed_kmh'] or 0:.0f} km/h)"
            for r in best))
    st.caption("Complete: tracking has passed the end of the window by 10 s of match time. \"-\": under the thresholds "
               "of Gold (60 seconds with a known owner, 10 opponent passes).")


def possession_bar(state: live.MatchState, colors: dict[str, str], names: dict | None) -> None:
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
    now = f" · now: {live.team_name(state, owner, names)}" if owner else " · now: ball dead or contested"
    st.caption(f"Possession {home:.0%} - {away:.0%} over {seconds // 60} min with a known owner{now}")


@st.fragment(run_every=1.0)
def live_view() -> None:
    states = feed.snapshot()
    if feed.error:
        st.warning(f"Kafka: {feed.error}")
    now_ms = int(time.time() * 1000)
    playing = live.now_playing(states, now_ms)
    if not playing:
        st.info("No match live right now.")
        st.page_link("sections/replay.py", label="Watch a stored match in Replay", icon=":material/replay:")
        st.caption("A match goes live when it is replayed into Kafka: `make replay MATCH=m001 SPEED=5`.")
        return
    st.markdown("<div class='ml-kicker'>NOW PLAYING</div>" + "".join(
        cards.badge(f"{live.team_name(states[m], 'HOME', fan_names(m))} {live.score(states[m])[0]} - "
                    f"{live.score(states[m])[1]} {live.team_name(states[m], 'AWAY', fan_names(m))}", "gold")
        for m in playing), unsafe_allow_html=True)
    chosen = st.session_state.get("match_id")          # the sidebar match opens directly when it is playing
    match = st.selectbox("Match", playing, index=playing.index(chosen) if chosen in playing else 0,
                         format_func=lambda m: f"{live.team_name(states[m], 'HOME', fan_names(m))} v "
                                               f"{live.team_name(states[m], 'AWAY', fan_names(m))}")
    state = states[match]
    status, colors = live.status(state, now_ms), colors_of(state)
    home_goals, away_goals = live.score(state)
    now_ts = live.clock(state, now_ms)

    names = fan_names(match)
    st.markdown(f"<h2 style='text-align:center;margin:0'>{live.team_name(state, 'HOME', names)} {home_goals} - "
                f"{away_goals} {live.team_name(state, 'AWAY', names)}</h2>", unsafe_allow_html=True)
    period = "Full time" if status == "full_time" else f"Period {state.period}" if state.period else ""
    message = STATUS_TEXT.get(status)
    st.markdown(f"<p style='text-align:center;font-size:1.3rem'>{clock.running(now_ts, None, *live.bounds(state)) if now_ts is not None else '--:--'}"
                f" · {period}{' · ' + message if message else ''}</p>", unsafe_allow_html=True)

    left, right = st.columns([3, 1])
    with left:
        frame = live.current_frame(state)
        ball = (state.ball[2], state.ball[3]) if state.ball else None
        side = live.home_attacks_right(state)
        selected = st.session_state.get("live_player", {}).get(match)
        clicked = pitch.show(
            key="live_pitch", colors=colors, selected=selected, message=message,
            players={pid: [p.get("team_id"), p.get("shirt_number"), p.get("short_name")] for pid, p in state.players.items()},
            frame=pitch.frame_list(frame[0], ball, frame[1]) if frame and status != "gap" else None,
            arrows=None if side is None else {"home": "right" if side else "left"})
        if clicked:
            st.session_state["live_player"] = {**st.session_state.get("live_player", {}), match: clicked}
            selected = clicked
        st.caption("Click a player for his stats so far. As the camera sees it: teams switch ends at half-time (arrows: "
                   "direction of attack). Lighter dots are positions estimated by SkillCorner, not seen by the camera.")
    with right:
        if selected and selected in state.players:
            player_panel(state, selected, colors, names)
            st.divider()
        possession_bar(state, colors, names)
        st.markdown("**Last event**")
        st.write(live.event_line(state, names) or "Nothing yet")
        st.markdown("**Team shape now** (outfield players, C1)")
        shape = live.team_shape(state, frame[1]) if frame and status == "live" else {}
        if shape:
            st.dataframe(pd.DataFrame([{"team": live.team_name(state, t, names), "width (m)": w, "length (m)": ln}
                                       for t, (w, ln) in shape.items()]).rename(columns={"length (m)": "outfield block length (m)"}),
                         hide_index=True)
        else:
            st.caption("Shown while positions arrive.")
    with st.container(border=True):
        five_minutes(state, feed.stats(state.replay_id) if state.replay_id else [], names)
    st.caption(f"{feed.messages:,} Kafka messages read. {CREDIT}")


live_view()
