"""goalmoment.py: the second a goal goes in, from the ball. The score of Live changes then; Gold has the same rule in
the dbt model gold_events (goal_ts), and tests/dbt checks that both give the same second.

A goal event's ts is the start of the possession that ended with the shot: the ball is not in the goal yet. Within
GOAL_WINDOW_S seconds after it, the goal moment is the first second with the ball past the goal line the team attacks,
between the posts (ball_in_goal). The ball is extrapolated after many shots and the camera often cuts away, so
otherwise it is the second the ball was nearest the goal mouth (ball_nearest_goal), known once the window is over.
Positions are in Silver's frame: HOME attacks toward x = 105.
"""

import math

GOAL_WINDOW_S = 10
PITCH_L, HALF_W = 105.0, 34.0
POST_HALF_WIDTH = 3.66


def goal_moment(
    team: str, event_ts: int, ball: list[tuple[int, float, float]], latest_ts: int
) -> tuple[int, str] | None:
    """(second, method), or None while it cannot be known yet. ball: (ts, x, y) seconds of the ball around the goal;
    latest_ts: the latest second of the match received so far."""
    goal_x = PITCH_L if team == "HOME" else 0.0
    window = sorted(b for b in ball if event_ts <= b[0] <= event_ts + GOAL_WINDOW_S and b[1] is not None)
    for ts, x, y in window:
        if (x > goal_x if team == "HOME" else x < goal_x) and abs(y - HALF_W) <= POST_HALF_WIDTH:
            return ts, "ball_in_goal"
    if latest_ts < event_ts + GOAL_WINDOW_S:
        return None
    if not window:
        return event_ts, "event_start"
    nearest = min(window, key=lambda b: (math.hypot(b[1] - goal_x, b[2] - HALF_W), b[0]))
    return nearest[0], "ball_nearest_goal"
