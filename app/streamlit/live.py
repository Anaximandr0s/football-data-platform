"""live.py: the state of a match being replayed, rebuilt from Kafka messages. Pure functions: no Kafka, no Streamlit.

`apply(state, table, record, kafka_ms)` takes one message and returns a new state; the other functions read a state.

A topic keeps every past replay. Every message carries the Kafka header replay_id ("m001-20261116T101503Z", set by
producer_foot), so one MatchState holds exactly one replay: `route` sends a message to its replay's state, ignores an
older replay of a match and messages without the header. Inside a replay the order of the topics does not matter.
The state keeps the coordinates of the replayed tables (origin bottom-left, attack directions as in the source, teams
switch ends at half-time); `silver_frame` gives the frame to draw in Silver's frame, like every pitch of the app.
"""
from dataclasses import dataclass, field, replace

import clock as football_clock  # live.clock (below) is the replay second now
import goalmoment
import playerstats

FULL_FRAME = 22
CHUNK = 64                                               # seconds per frozen chunk of a player's history
KEY_EVENTS = {"goal": "Goal", "shot": "Shot", "tackle": "Tackle", "foul": "Foul"}
STALLED_AFTER_S = 300  # match seconds without any tracking: longer than any camera gap of the source (143 s)
BALL_TRACK_S = 30      # seconds of ball kept to find when a goal went in (goalmoment needs 10 after the event)


@dataclass(frozen=True)
class MatchState:
    match_id: str
    start_ms: int = -1                                   # Kafka time of the matches message of this replay
    replay_id: str | None = None
    info: dict = field(default_factory=dict)             # the matches record
    players: dict = field(default_factory=dict)          # player_id -> players record
    frames: dict = field(default_factory=dict)           # ts -> (kafka_ms, {player_id: (x, y, is_detected)})
    ball: tuple | None = None                            # (ts, period, x, y, kafka_ms)
    possession: dict = field(default_factory=dict)       # ts -> (team_id, kafka_ms)
    goals: dict = field(default_factory=dict)            # event_id -> (ts, team_id, player_id, kafka_ms, goal second or None)
    ball_track: dict = field(default_factory=dict)       # ts -> (period, x, y): the latest seconds of the ball
    last_event: tuple | None = None                      # (ts, event_id, type, team_id, player_id, kafka_ms)
    first_tracking: tuple | None = None                  # (ts, kafka_ms) of the earliest tracked second seen
    last_tracking: tuple | None = None                   # (ts, kafka_ms) of the latest tracked second seen
    period: int | None = None
    seconds: dict = field(default_factory=dict)          # player_id -> (chunks, tail) of (ts, period, x, y, speed, detected, kafka_ms)


def apply(state: MatchState, table: str, rec: dict, kafka_ms: int) -> MatchState:
    """One Kafka message in, the new state out. `table` is the replayed table the topic carries."""
    if table == "matches":                                # a repeated matches message keeps the first start
        return replace(state, info=rec, start_ms=kafka_ms if state.start_ms < 0 else state.start_ms)
    if table == "players":
        return replace(state, players={**state.players, rec["player_id"]: rec})
    if table == "tracking":
        return _settle(_tracking(state, rec, kafka_ms))
    if table == "ball":
        return _settle(_ball(state, rec, kafka_ms))
    if table == "events":
        return _settle(_event(state, rec, kafka_ms))
    raise ValueError(f"unknown table {table}")


def route(states: dict[str, MatchState], replay_id: str | None, table: str, rec: dict,
          kafka_ms: int) -> dict[str, MatchState]:
    """states: match_id -> the state of its latest replay. A message without replay_id (sent before the header
    existed) or from an older replay of the match is ignored; a newer replay replaces the older state."""
    if replay_id is None:
        return states
    current = states.get(rec["match_id"])
    if current is not None and current.replay_id is not None and replay_id < current.replay_id:
        return states                                     # same match prefix: the UTC start sorts the replays
    if current is None or current.replay_id != replay_id:
        current = MatchState(rec["match_id"], replay_id=replay_id)
    return {**states, rec["match_id"]: apply(current, table, rec, kafka_ms)}


def _tracking(state: MatchState, rec: dict, kafka_ms: int) -> MatchState:
    ts, pid = rec["ts"], rec["player_id"]
    # every second of every player is kept for the live player stats, appended to small frozen chunks so that a
    # message copies at most CHUNK items, not the whole history
    item = (ts, rec["period"], rec["x"], rec["y"], rec.get("speed_kmh"), bool(rec.get("is_detected")), kafka_ms)
    chunks, tail = state.seconds.get(pid, ((), ()))
    history = (chunks, tail + (item,)) if len(tail) < CHUNK else (chunks + (tail,), (item,))
    state = replace(state, seconds={**state.seconds, pid: history})
    frames = state.frames
    if ts not in frames and len(frames) >= 2 and ts < min(frames):
        return state                                      # older than both frames kept: nothing more to show
    ms, positions = frames.get(ts, (kafka_ms, {}))
    positions = {**positions, rec["player_id"]: (rec["x"], rec["y"], rec.get("is_detected"))}
    frames = {**frames, ts: (max(ms, kafka_ms), positions)}
    frames = {t: frames[t] for t in sorted(frames)[-2:]}   # the second being received and the one before
    first = state.first_tracking if state.first_tracking and state.first_tracking[0] <= ts else (ts, kafka_ms)
    last = state.last_tracking if state.last_tracking and state.last_tracking[0] >= ts else (ts, kafka_ms)
    return replace(state, frames=frames, first_tracking=first, last_tracking=last,
                   period=rec["period"] if last[0] == ts else state.period)


def _ball(state: MatchState, rec: dict, kafka_ms: int) -> MatchState:
    possession = state.possession
    if rec.get("possession") in ("HOME", "AWAY"):
        possession = {**possession, rec["ts"]: (rec["possession"], kafka_ms)}
    ball = state.ball
    if ball is None or rec["ts"] >= ball[0]:
        ball = (rec["ts"], rec["period"], rec["x"], rec["y"], kafka_ms)
    track = {**state.ball_track, rec["ts"]: (rec["period"], rec["x"], rec["y"])}
    track = {t: v for t, v in track.items() if t >= max(track) - BALL_TRACK_S}
    return replace(state, ball=ball, possession=possession, ball_track=track)


def _event(state: MatchState, rec: dict, kafka_ms: int) -> MatchState:
    kind = rec["type"]
    if kind not in KEY_EVENTS:                            # passes, pressures and runs: too frequent for a headline
        return state
    goals = state.goals
    if kind == "goal":
        moment = goals.get(rec["event_id"], (None,) * 5)[4]          # a repeated message keeps the second found
        goals = {**goals, rec["event_id"]: (rec["ts"], rec["team_id"], rec["player_id"], kafka_ms, moment)}
    item = (rec["ts"], rec["event_id"], kind, rec["team_id"], rec["player_id"], kafka_ms)
    last = state.last_event if state.last_event and state.last_event[:2] > item[:2] else item
    return replace(state, goals=goals, last_event=last)


def _latest(state: MatchState) -> int:
    return max(state.last_tracking[0] if state.last_tracking else -1, state.ball[0] if state.ball else -1)


def _settle(state: MatchState) -> MatchState:
    """Give each goal still waiting the second the ball went in (goalmoment), once the ball tells it."""
    pending = {e: g for e, g in state.goals.items() if g[4] is None}
    if not pending or not state.info:
        return state
    p1, p2 = state.info.get("home_side_p1"), state.info.get("home_side_p2")
    ball = [(t, *playerstats.flip_xy(x, y, period, p1, p2)) for t, (period, x, y) in state.ball_track.items()
            if x is not None]
    goals = dict(state.goals)
    for event_id, (ts, team, pid, ms, _) in pending.items():
        found = goalmoment.goal_moment(team, ts, ball, _latest(state))
        if found:
            goals[event_id] = (ts, team, pid, ms, found[0])
    return replace(state, goals=goals)


# ---------------------------------------------------------------- reading a state

def score(state: MatchState) -> tuple[int, int]:
    """Goals whose ball is in the goal: the score changes when the ball goes in, not when the attack starts."""
    teams = [g[1] for g in state.goals.values() if g[4] is not None]
    return teams.count("HOME"), teams.count("AWAY")


def possession_share(state: MatchState) -> tuple[float, float, int] | None:
    """(HOME share, AWAY share, seconds with a known owner) over the replay so far; None before the first one."""
    teams = [p[0] for p in state.possession.values()]
    if not teams:
        return None
    home = teams.count("HOME") / len(teams)
    return home, 1 - home, len(teams)


def current_owner(state: MatchState) -> str | None:
    """Team in possession at the latest ball second, None when the ball is dead or nobody controls it."""
    if state.ball is None:
        return None
    owner = state.possession.get(state.ball[0])
    return owner[0] if owner else None


def current_frame(state: MatchState) -> tuple[int, dict] | None:
    """Latest complete second of positions (22 players), else the latest partial one."""
    if not state.frames:
        return None
    for ts in sorted(state.frames, reverse=True):
        if len(state.frames[ts][1]) >= FULL_FRAME:
            return ts, state.frames[ts][1]
    ts = max(state.frames)
    return ts, state.frames[ts][1]


def ms_per_second(state: MatchState) -> float | None:
    """Real milliseconds per match second of this replay (1000 at x1, about 200 at x5)."""
    first, last = state.first_tracking, state.last_tracking
    if not first or not last or last[0] <= first[0]:
        return None
    return (last[1] - first[1]) / (last[0] - first[0])


def clock(state: MatchState, now_ms: int) -> int | None:
    """Match second now. Runs on through camera gaps by extrapolating from the last tracked second."""
    if state.last_tracking is None:
        return None
    ts, ms = state.last_tracking
    pace = ms_per_second(state)
    if pace:
        ts += max(0, int((now_ms - ms) / pace))
    end = state.info.get("p2_end_ts")
    return min(ts, end) if end is not None else ts


def status(state: MatchState, now_ms: int) -> str:
    """waiting | live | gap (camera off the pitch) | stalled (no data for long: replay stopped?) | full_time."""
    if not state.info or state.last_tracking is None:
        return "waiting"
    last_ts, last_ms = state.last_tracking
    if last_ts >= state.info.get("p2_end_ts", float("inf")):
        return "full_time"
    pace = ms_per_second(state) or 1000.0
    if now_ms - last_ms <= 3 * pace + 500:                # a few match seconds of slack for the page refresh
        return "live"
    return "stalled" if (now_ms - last_ms) / pace > STALLED_AFTER_S else "gap"


PLAYING = ("waiting", "live", "gap")


def now_playing(states: dict[str, MatchState], now_ms: int) -> list[str]:
    """Matches being replayed right now: started, not at full time, not silent for longer than any camera gap."""
    return sorted(m for m, s in states.items() if s.info and status(s, now_ms) in PLAYING)


def team_shape(state: MatchState, positions: dict) -> dict[str, tuple[float, float]]:
    """C1 for one second: (width, length) in metres per team, outfield players only."""
    out = {}
    for team in ("HOME", "AWAY"):
        pts = [xy for pid, xy in positions.items()
               if state.players.get(pid, {}).get("team_id") == team
               and state.players.get(pid, {}).get("position") != "GK"]
        if len(pts) >= 2:
            ys, xs = [p[1] for p in pts], [p[0] for p in pts]
            out[team] = (round(max(ys) - min(ys), 1), round(max(xs) - min(xs), 1))
    return out


def team_name(state: MatchState, team: str, names: dict | None = None) -> str:
    """The name fans use when the page knows it (`names`, from Gold), else the source's full name."""
    if names and names.get(team):
        return names[team]
    return state.info.get("home_team" if team == "HOME" else "away_team") or team


def bounds(state: MatchState) -> tuple[int, int | None]:
    """(p1_start_ts, p2_start_ts) of the replayed match: what the football clock needs."""
    return state.info.get("p1_start_ts") or 0, state.info.get("p2_start_ts")


def event_line(state: MatchState, names: dict | None = None) -> str | None:
    """'Goal, 46', Adelaide United (Z. Clough)': the latest goal, shot, tackle or foul, on the football clock."""
    if state.last_event is None:
        return None
    ts, _, kind, team, pid, _ = state.last_event
    who = state.players.get(pid, {}).get("short_name")
    return (f"{KEY_EVENTS[kind]}, {football_clock.label(ts, None, *bounds(state))}, {team_name(state, team, names)}"
            + (f" ({who})" if who else ""))


def player_stats(state: MatchState, player_id: str) -> playerstats.PlayerStats:
    """Distance, sprints, top speed and heatmap of a player over the replay so far, with the formulas of Gold."""
    p1, p2 = state.info.get("home_side_p1"), state.info.get("home_side_p2")
    latest = {}                                           # a repeated message (at-least-once) counts once
    for ts, period, x, y, speed, detected, _ in _history(state.seconds.get(player_id, ((), ()))):
        latest[ts] = (period, x, y, speed, detected)
    seconds = [playerstats.Second(ts, *playerstats.silver_xy(x, y, period, p1, p2), speed, detected)
               for ts, (period, x, y, speed, detected) in latest.items()]
    return playerstats.player_stats(seconds)


def _history(history: tuple) -> list:
    chunks, tail = history
    return [item for chunk in (*chunks, tail) for item in chunk]


def silver_frame(state: MatchState) -> tuple[int, tuple | None, dict] | None:
    """(ts, ball, {player_id: (x, y, is_detected)}) of the current frame in Silver's frame: HOME attacks toward
    x = 105 in both halves, as on the Replay and Player pages (players clipped to the pitch like Silver, the ball not)."""
    current = current_frame(state)
    if current is None:
        return None
    ts, positions = current
    p1, p2 = state.info.get("home_side_p1"), state.info.get("home_side_p2")
    period = football_clock.period_of(ts, state.info.get("p2_start_ts"))
    players = {pid: (*playerstats.silver_xy(x, y, period, p1, p2), det) for pid, (x, y, det) in positions.items()}
    ball = None
    if state.ball is not None:
        _, ball_period, bx, by, _ = state.ball
        ball = tuple(round(v, 2) for v in playerstats.flip_xy(bx, by, ball_period, p1, p2))
    return ts, ball, players
