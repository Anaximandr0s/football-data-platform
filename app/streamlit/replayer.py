"""replayer.py: the data of the Replay page (docs/product.md: R1, S1), from gold_replay_frames and the Gold tables.
Pure functions: no Streamlit, no DuckDB.

The match is sent once to the pitch component (pitch.js plays it, interpolating between consecutive seconds); the
panel next to it is recomputed in Python for the second the visitor is watching, with only what happened up to then.
"""
import math

import numpy as np
import pandas as pd

import clock
import playerstats


def payload(frames: pd.DataFrame, key: str) -> dict:
    """gold_replay_frames rows of one match -> {key, ids, t, xy}: one list per tracked second, [ball x, ball y, then
    x, y, detected (1/0) of each player in `ids` order], positions in whole centimetres (Silver keeps 2 decimals, so
    nothing is lost), None when absent."""
    players = frames[frames.object_type == "player"]
    ids = sorted(players.object_id.unique())
    t = np.sort(frames.ts.unique())
    row = {ts: i for i, ts in enumerate(t)}
    grid = np.full((len(t), 2 + 3 * len(ids)), np.nan)
    balls = frames[frames.object_type == "ball"]
    grid[balls.ts.map(row), 0] = balls.x * 100
    grid[balls.ts.map(row), 1] = balls.y * 100
    col = players.object_id.map({pid: 2 + 3 * j for j, pid in enumerate(ids)})
    rows = players.ts.map(row)
    grid[rows, col] = players.x * 100
    grid[rows, col + 1] = players.y * 100
    grid[rows, col + 2] = players.is_detected.astype(float)
    xy = [[None if math.isnan(v) else int(round(v)) for v in r] for r in grid]
    return {"key": key, "ids": ids, "t": [int(v) for v in t], "xy": xy}


def position_at(data: dict, ts: int, object_id: str) -> tuple[float, float] | None:
    """The position the browser starts from at second ts (metres), as it decodes the payload; None if absent."""
    if ts not in data["t"]:
        return None
    r = data["xy"][data["t"].index(ts)]
    o = 0 if object_id == "ball" else 2 + 3 * data["ids"].index(object_id)
    return None if r[o] is None else (r[o] / 100, r[o + 1] / 100)


def clock_labels(first_ts: int, last_ts: int, p1_start_ts: int, p2_start_ts: int | None) -> list[str]:
    """The running football clock of every second from first_ts to last_ts (the browser shows them, so the clock rule
    stays in clock.py)."""
    return [clock.running(ts, None, p1_start_ts, p2_start_ts) for ts in range(first_ts, last_ts + 1)]


def goals(events: pd.DataFrame, p1_start_ts: int, p2_start_ts: int | None) -> list[list]:
    """[ts, team, "62' Goodwin"] of every goal of one match (gold_events), in order."""
    g = events[events.type == "goal"].sort_values("ts")
    return [[int(r.ts), r.team_id, f"{clock.label(r.ts, r.period, p1_start_ts, p2_start_ts)} {r.player_short_name}"]
            for r in g.itertuples()]


def score_at(goal_list: list[list], ts: int) -> tuple[int, int]:
    home = sum(1 for g in goal_list if g[0] <= ts and g[1] == "HOME")
    return home, sum(1 for g in goal_list if g[0] <= ts) - home


def possession_until(frames: pd.DataFrame, ts: int) -> tuple[int, int]:
    """(HOME, AWAY) seconds with a known owner of the ball up to second ts (F2, as gold_match_timeline counts them)."""
    ball = frames[(frames.object_type == "ball") & (frames.ts <= ts)]
    return int((ball.possession == "HOME").sum()), int((ball.possession == "AWAY").sum())


def windows_until(timeline: pd.DataFrame, ts: int) -> pd.DataFrame:
    """The 5-minute windows of gold_match_timeline already over at second ts (both teams side by side), newest first:
    a window still being played is not shown, its Gold values would tell the future."""
    done = timeline[timeline.window_end_ts <= ts + 1]
    home = done[done.team_id == "HOME"].set_index("window_index")
    away = done[done.team_id == "AWAY"].set_index("window_index")
    out = pd.DataFrame({"window_label": home.window_label, "possession_greyed": home.possession_greyed,
                        "home_possession": home.possession_share, "away_possession": away.possession_share,
                        "home_passes": home.passes, "away_passes": away.passes,
                        "home_xthreat": home.xthreat_successful_passes, "away_xthreat": away.xthreat_successful_passes})
    return out.sort_index(ascending=False)


def player_until(frames: pd.DataFrame, player_id: str, ts: int) -> playerstats.PlayerStats:
    """Distance, sprints, top speed and heatmap of one player up to second ts, with the formulas of Live and Gold."""
    rows = frames[(frames.object_id == player_id) & (frames.ts <= ts)]
    speed = rows.speed_kmh.astype(object).where(rows.speed_kmh.notna(), None)
    return playerstats.player_stats([playerstats.Second(int(t), float(x), float(y), s, bool(d))
                                     for t, x, y, s, d in zip(rows.ts, rows.x, rows.y, speed, rows.is_detected,
                                                              strict=True)])


def space_now(frames: pd.DataFrame, ts: int) -> float | None:
    """HOME share of the pitch (S1) at the last tracked second up to ts."""
    ball = frames[(frames.object_type == "ball") & (frames.ts <= ts)]
    return None if ball.empty else float(ball.sort_values("ts").home_space_share.iloc[-1])
