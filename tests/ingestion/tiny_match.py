"""A tiny hand-made SkillCorner match: two periods of 4 seconds, 4 players on the pitch."""
import json

import pandas as pd


def _player(pid, team_id, number, role, start, end, first, last):
    return {"id": pid, "team_id": team_id, "number": number,
            "first_name": f"{first} ", "last_name": last, "short_name": f"{first[0]}. {last}",
            "player_role": {"acronym": role},
            "playing_time": {"total": {"start_frame": start, "end_frame": end}}}


def match_info() -> dict:
    """Two periods (frames 10-49 and 60-99) at 10 fps; 5 players, one of whom never plays."""
    return {
        "home_team": {"id": 100, "name": "Home FC", "short_name": "Home"},
        "away_team": {"id": 200, "name": "Away United", "short_name": "Away"},
        "home_team_score": 1, "away_team_score": 0,
        "home_team_side": ["left_to_right", "right_to_left"],
        "pitch_length": 105, "pitch_width": 68,
        "match_periods": [{"period": 1, "start_frame": 10, "end_frame": 49},
                          {"period": 2, "start_frame": 60, "end_frame": 99}],
        "players": [
            _player(1, 100, 1, "GK", 10, 99, "Gil", "Keeper"),
            _player(2, 100, 9, "CF", 10, 49, "Sam", "Striker"),
            _player(3, 100, 20, "CF", 50, 99, "Tom", "Sub"),
            _player(4, 200, 5, "CB", 10, 99, "Ann", "Defender"),
            {"id": 5, "team_id": 100, "number": 30, "first_name": "Bench", "last_name": "Warmer",
             "playing_time": {"total": None}},
        ],
    }


def _frames():
    """10 fps, kick-off at frame 10. Second 2 (frames 30-39) is a gap: no player, no ball."""
    lines = []
    for f in range(100):
        ts, off = (f - 10) // 10, (f - 10) % 10 * 0.1
        period = 1 if 10 <= f <= 49 else 2 if f >= 60 else None
        if period is None or ts == 2:
            frame = {"frame": f, "period": period,
                     "ball_data": {"x": None, "y": None, "z": None}, "player_data": []}
        else:
            group = {0: "home team", 1: "away team"}.get(ts)                  # unknown from second 3 on
            frame = {"frame": f, "period": period, "ball_data": {"x": off, "y": 0.0, "z": 0.3},
                     "possession": {"player_id": None, "group": group},
                     "player_data": [
                         {"player_id": 1, "x": -52.5 + ts + off, "y": 0.0, "is_detected": True},  # +1 m/s
                         {"player_id": 2, "x": 60.0, "y": 0.0, "is_detected": False},  # outside the pitch
                         {"player_id": 3, "x": 10.0, "y": 5.0, "is_detected": True},
                         {"player_id": 4, "x": 0.0, "y": 0.0, "is_detected": ts % 2 == 0},
                         {"player_id": 99, "x": 0.0, "y": 0.0}]}              # not in the lineup
        lines.append(json.dumps(frame))
    return lines


def _events():
    cols = ["frame_start", "period", "team_id", "player_id", "event_type", "end_type",
            "team_score", "opponent_team_score", "x_start", "y_start", "x_end", "y_end",
            "player_targeted_id", "player_targeted_x_reception", "player_targeted_y_reception",
            "pass_outcome", "event_subtype", "player_targeted_xthreat", "player_targeted_dangerous",
            "xthreat", "dangerous", "targeted", "received", "speed_avg_band", "lead_to_shot"]
    nan = float("nan")
    rows = [
        (15, 1, 200, 4, "on_ball_engagement", "indirect_regain", 0, 0, 10, 0, 12, 1, nan, nan, nan, nan,
         "pressing", nan, nan, nan, nan, nan, nan, "running", False),
        (25, 1, 100, 1, "player_possession", "pass", 0, 0, -10, 0, -5, 0, 2, -20, 5, "successful",
         nan, 0.04, True, nan, nan, nan, nan, "jogging", True),
        (25, 1, 100, 3, "off_ball_run", nan, 0, 0, 0, 0, 1, 1, nan, nan, nan, nan,
         "behind", nan, nan, 0.12, True, True, False, "sprinting", True),
        (35, 1, 100, 2, "player_possession", "shot", 0, 0, 40, 0, 52.5, 0, nan, nan, nan, nan,
         nan, nan, nan, nan, nan, nan, nan, nan, True),
        (45, 1, 200, 4, "on_ball_engagement", "direct_regain", 0, 1, 5, 5, 6, 6, nan, nan, nan, nan,
         "counter_press", nan, nan, nan, nan, nan, nan, "hsr", False),
        (65, 2, 200, 4, "on_ball_engagement", "foul_committed", 0, 1, 5, 5, 6, 6, nan, nan, nan, nan,
         "other", nan, nan, nan, nan, nan, nan, "jogging", False),
        (65, 2, 100, 77, "player_possession", "pass", 1, 0, 0, 0, 1, 1, nan, nan, nan, nan,
         nan, nan, nan, nan, nan, nan, nan, nan, False),
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["team_in_possession_phase_type"] = "build_up"
    df["team_out_of_possession_phase_type"] = "high_block"
    return df
