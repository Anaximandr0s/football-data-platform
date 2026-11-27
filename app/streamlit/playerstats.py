"""playerstats.py: the per-player formulas shared by the Live and Replay pages, written once.

They are the formulas of Silver and Gold, so the live values at full time equal Gold (tests/app/test_playerstats.py):
  position   Silver frame: mirrored where HOME attacks toward x = 0 in that period, clipped to 105 x 68, 2 decimals
  distance   sum(speed_kmh / 3.6) over the seconds with a speed (gold_player_match_stats.distance_m)
  sprints    efforts: a second above 25 km/h that does not continue a sprint second of ts - 1 (sprint_count)
  top speed  best speed held over two consecutive seconds, min(v(ts - 1), v(ts)), with the positions of ts - 2, ts - 1
             and ts detected (gold_player_card, F5): one fast second is often one bad position
  heatmap    seconds per cell of the 6 x 4 grid (gold_zone_occupancy)
Pure functions: no Kafka, no Streamlit.
"""

import math
from dataclasses import dataclass

PITCH_L, PITCH_W = 105.0, 68.0
ZONES_X, ZONES_Y = 6, 4
SPRINT_KMH = 25.0
MAX_SPEED_KMH = 40.0  # Silver's rule: faster is a jump between positions, not a run (spark/silver/config.py)
RIGHT_TO_LEFT = "right_to_left"


@dataclass(frozen=True)
class Second:
    ts: int
    x: float  # Silver frame (see silver_xy)
    y: float
    speed_kmh: float | None
    is_detected: bool


@dataclass(frozen=True)
class PlayerStats:
    tracked_seconds: int
    distance_m: float
    sprint_count: int
    top_speed_kmh: float | None
    zones: dict  # zone_id -> seconds


def flip_xy(x: float, y: float, period: int, home_side_p1: str | None, home_side_p2: str | None) -> tuple:
    """Silver's frame without clipping (the ball keeps a position off the pitch): mirrored in a period where HOME
    attacks toward x = 0."""
    flip = (period == 1 and home_side_p1 == RIGHT_TO_LEFT) or (period == 2 and home_side_p2 == RIGHT_TO_LEFT)
    return (PITCH_L - x, PITCH_W - y) if flip else (x, y)


def silver_xy(x: float, y: float, period: int, home_side_p1: str | None, home_side_p2: str | None) -> tuple:
    """The position of a player as Silver stores it: HOME attacks toward x = 105 in both periods, inside the pitch."""
    x, y = flip_xy(x, y, period, home_side_p1, home_side_p2)
    return round(min(max(x, 0.0), PITCH_L), 2), round(min(max(y, 0.0), PITCH_W), 2)


def zone_of(x: float, y: float) -> int:
    """Cell of the 6 x 4 grid, as gold_zone_occupancy: x = 105 and y = 68 stay in the last cell."""
    zx = min(math.floor(x / PITCH_L * ZONES_X), ZONES_X - 1)
    zy = min(math.floor(y / PITCH_W * ZONES_Y), ZONES_Y - 1)
    return zy * ZONES_X + zx


def player_stats(seconds: list[Second]) -> PlayerStats:
    """Stats of one player over the seconds seen so far (any order, one per ts)."""
    distance, sprints, top, zones = 0.0, 0, None, {}
    prev = before = None
    for s in sorted(seconds, key=lambda s: s.ts):
        if s.speed_kmh is not None and s.speed_kmh > MAX_SPEED_KMH:  # Live gets bronze's raw speed
            s = Second(s.ts, s.x, s.y, None, s.is_detected)
        if s.speed_kmh is not None:
            distance += s.speed_kmh / 3.6
        sprint = s.speed_kmh is not None and s.speed_kmh > SPRINT_KMH
        prev_sprint = prev is not None and prev.speed_kmh is not None and prev.speed_kmh > SPRINT_KMH
        if sprint and not (prev_sprint and s.ts - prev.ts == 1):
            sprints += 1
        held = (
            prev is not None
            and before is not None
            and s.ts - prev.ts == 1
            and prev.ts - before.ts == 1
            and s.is_detected
            and prev.is_detected
            and before.is_detected
            and s.speed_kmh is not None
            and prev.speed_kmh is not None
        )
        if held:
            speed = min(s.speed_kmh, prev.speed_kmh)
            top = speed if top is None else max(top, speed)
        zone = zone_of(s.x, s.y)
        zones[zone] = zones.get(zone, 0) + 1
        before, prev = prev, s
    return PlayerStats(len(seconds), distance, sprints, top, zones)


def heat_cells(zones: dict) -> list[float]:
    """Share of the seconds in each cell, in zone_id order (the pitch component's heat layer)."""
    total = sum(zones.values()) or 1
    return [zones.get(z, 0) / total for z in range(ZONES_X * ZONES_Y)]
