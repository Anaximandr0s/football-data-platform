"""live.py: the state of a match being replayed, rebuilt from Kafka messages. Pure functions: no Kafka, no Streamlit.

`apply(state, table, record, kafka_ms)` takes one message and returns a new state; the other functions read a state.

A topic keeps every past replay, and messages of different topics do not arrive in a fixed order. So every stored item
keeps the Kafka time of its message, and a replay starts at the Kafka time of its `matches` message: anything older
belongs to a previous replay and is dropped. The result does not depend on the order of the topics.
Coordinates are those of the replayed tables: origin bottom-left, attack directions as in the source (teams switch
ends at half-time).
"""
from dataclasses import dataclass, field, replace

import clock as football_clock  # live.clock (below) is the replay second now
import playerstats

FULL_FRAME = 22
CHUNK = 64                                               # seconds per frozen chunk of a player's history
KEY_EVENTS = {"goal": "Goal", "shot": "Shot", "tackle": "Tackle", "foul": "Foul"}
STALLED_AFTER_S = 300  # match seconds without any tracking: longer than any camera gap of the source (143 s)


@dataclass(frozen=True)
class MatchState:
    match_id: str
    start_ms: int = -1                                   # Kafka time of the matches message of the latest replay
    info: dict = field(default_factory=dict)             # the matches record
    players: dict = field(default_factory=dict)          # player_id -> players record
    frames: dict = field(default_factory=dict)           # ts -> (kafka_ms, {player_id: (x, y, is_detected)})
    ball: tuple | None = None                            # (ts, period, x, y, kafka_ms)
    possession: dict = field(default_factory=dict)       # ts -> (team_id, kafka_ms)
    goals: dict = field(default_factory=dict)            # event_id -> (ts, team_id, player_id, kafka_ms)
    last_event: tuple | None = None                      # (ts, event_id, type, team_id, player_id, kafka_ms)
    first_tracking: tuple | None = None                  # (ts, kafka_ms) of the earliest tracked second seen
    last_tracking: tuple | None = None                   # (ts, kafka_ms) of the latest tracked second seen
    period: int | None = None
    seconds: dict = field(default_factory=dict)          # player_id -> (chunks, tail) of (ts, period, x, y, speed, detected, kafka_ms)


def apply(state: MatchState, table: str, rec: dict, kafka_ms: int) -> MatchState:
    """One Kafka message in, the new state out. `table` is the replayed table the topic carries."""
    if table == "matches":
        return _new_replay(state, rec, kafka_ms) if kafka_ms > state.start_ms else state
    if kafka_ms < state.start_ms:
        return state
    if table == "players":
        return replace(state, players={**state.players, rec["player_id"]: rec})
    if table == "tracking":
        return _tracking(state, rec, kafka_ms)
    if table == "ball":
        return _ball(state, rec, kafka_ms)
    if table == "events":
        return _event(state, rec, kafka_ms)
    raise ValueError(f"unknown table {table}")


def _new_replay(state: MatchState, rec: dict, start: int) -> MatchState:
    """Keep only what was sent after the new replay started (its messages may have come before its matches row)."""
    def recent(item_ms: int) -> bool:
        return item_ms >= start

    def keep(item):
        return item if item is not None and recent(item[-1]) else None

    return MatchState(
        match_id=state.match_id, start_ms=start, info=rec, players=state.players,
        frames={ts: f for ts, f in state.frames.items() if recent(f[0])},
        ball=keep(state.ball),
        possession={ts: p for ts, p in state.possession.items() if recent(p[1])},
        goals={k: g for k, g in state.goals.items() if recent(g[-1])},
        last_event=keep(state.last_event), first_tracking=keep(state.first_tracking),
        last_tracking=keep(state.last_tracking), period=state.period if keep(state.last_tracking) else None,
        seconds={pid: ((), kept) for pid, history in state.seconds.items()
                 if (kept := tuple(v for v in _history(history) if recent(v[-1])))})


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
    return replace(state, ball=ball, possession=possession)


def _event(state: MatchState, rec: dict, kafka_ms: int) -> MatchState:
    kind = rec["type"]
    if kind not in KEY_EVENTS:                            # passes, pressures and runs: too frequent for a headline
        return state
    goals = state.goals
    if kind == "goal":
        goals = {**goals, rec["event_id"]: (rec["ts"], rec["team_id"], rec["player_id"], kafka_ms)}
    item = (rec["ts"], rec["event_id"], kind, rec["team_id"], rec["player_id"], kafka_ms)
    last = state.last_event if state.last_event and state.last_event[:2] > item[:2] else item
    return replace(state, goals=goals, last_event=last)


# ---------------------------------------------------------------- reading a state

def score(state: MatchState) -> tuple[int, int]:
    teams = [g[1] for g in state.goals.values()]
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


def home_attacks_right(state: MatchState) -> bool | None:
    """Direction HOME attacks in the current period, as given by the source."""
    if state.period not in (1, 2):
        return None
    return state.info.get(f"home_side_p{state.period}") == "left_to_right"
