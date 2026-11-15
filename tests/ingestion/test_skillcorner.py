"""Tests of skillcorner.py on a tiny hand-made match: no Docker, no download.

    make test        (or: python -m pytest -q)
"""
import json

import pandas as pd
import pytest

from ingestion.config import PITCH_L
from ingestion.schemas import SCHEMAS, write_parquet
from ingestion.skillcorner import build_match, build_players, parse_events, parse_tracking


def _player(pid, team_id, number, role, start, end, first, last):
    return {"id": pid, "team_id": team_id, "number": number,
            "first_name": f"{first} ", "last_name": last, "short_name": f"{first[0]}. {last}",
            "player_role": {"acronym": role},
            "playing_time": {"total": {"start_frame": start, "end_frame": end}}}


@pytest.fixture
def info():
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


def test_players_ids_names_and_playing_time(info):
    players, idmap, _ = build_players(info, "t1")
    assert list(players["player_id"]) == ["H01", "H02", "H03", "A01"]
    assert idmap[3] == ("H03", "HOME") and 5 not in idmap        # the bench player is never listed
    row = players.set_index("player_id").loc["H02"]
    assert row["name"] == "Sam Striker" and row["short_name"] == "S. Striker"
    assert (row["start_ts"], row["end_ts"]) == (0, 3)            # frames 10-49 -> seconds 0-3
    assert list(players["source_player_id"]) == [1, 2, 3, 4]    # SkillCorner id, stable across matches


def test_tracking_one_row_per_player_per_second_with_gaps(info):
    _, idmap, spans = build_players(info, "t1")
    tracking, ball, drops = parse_tracking(_frames(), info, idmap, spans, "t1")

    assert sorted(tracking["ts"].unique()) == [0, 1, 3, 5, 6, 7, 8]   # nothing invented in the gap
    assert (tracking.groupby("ts").size() == 3).all()                 # lineup players on the pitch only
    assert drops["player_not_in_lineup"] == 7
    assert drops["player_outside_playing_time"] == 7
    assert drops["ball_without_position"] == 1
    assert list(ball["ts"]) == [0, 1, 3, 5, 6, 7, 8]

    keeper = tracking[tracking["player_id"] == "H01"].set_index("ts")
    assert (keeper.loc[0, "x"], keeper.loc[0, "y"]) == (0.0, 34.0)    # centred coords + (52.5, 34)
    assert keeper.loc[1, "speed_kmh"] == pytest.approx(3.6)           # 1 m in 1 s
    assert keeper.loc[6, "speed_kmh"] == pytest.approx(3.6)
    assert keeper["speed_kmh"].isna().loc[[0, 3, 5]].all()            # no previous second: null, not 0

    striker = tracking[tracking["player_id"] == "H02"]
    assert (striker["x"] == 112.5).all() and striker["x"].max() > PITCH_L   # positions are not clipped
    assert not striker["is_detected"].any() and keeper["is_detected"].all()
    assert list(tracking[tracking["player_id"] == "A01"]["is_detected"]) == [True, False, False, False, True,
                                                                             False, True]


def test_ball_possession_uses_our_team_keys_and_stays_null_when_unknown(info):
    _, idmap, spans = build_players(info, "t1")
    _, ball, _ = parse_tracking(_frames(), info, idmap, spans, "t1")
    assert list(ball["possession"])[:2] == ["HOME", "AWAY"]
    assert ball["possession"].iloc[2:].isna().all()


def test_events_mapping_receiver_and_goal(info, tmp_path):
    _, idmap, _ = build_players(info, "t1")
    csv = tmp_path / "events.csv"
    _events().to_csv(csv, index=False)
    ev = parse_events(csv, info, idmap, "t1")
    actions = ev[ev["type"] != "run"]

    assert list(actions["type"]) == ["pressure", "pass", "goal", "tackle", "foul"]
    assert list(actions["ts"]) == [0, 1, 2, 3, 5]
    assert list(actions["event_id"]) == [f"t1-e{i:05d}" for i in range(1, 6)]   # runs do not shift them
    assert list(actions["team_id"]) == ["AWAY", "HOME", "HOME", "AWAY", "AWAY"]
    pas = ev[ev["type"] == "pass"].iloc[0]
    assert pas["receiver_id"] == "H02" and pas["x_end"] == 32.5 and pas["y_end"] == 39.0
    assert ev["receiver_id"].isna().sum() == 5                       # only passes have a receiver


def test_off_ball_runs_are_kept_as_type_run_with_their_own_ids(info, tmp_path):
    _, idmap, _ = build_players(info, "t1")
    csv = tmp_path / "events.csv"
    _events().to_csv(csv, index=False)
    ev = parse_events(csv, info, idmap, "t1")
    run = ev[ev["type"] == "run"].iloc[0]
    assert run["event_id"] == "t1-r00001" and run["player_id"] == "H03" and run["ts"] == 1
    assert (run["subtype"], run["xthreat"], run["dangerous"]) == ("behind", 0.12, True)
    assert (run["targeted"], run["received"], run["outcome"]) == (True, False, "n/a")
    assert ev.loc[ev["type"] != "run", ["targeted", "received"]].isna().all().all()


def test_event_context_columns(info, tmp_path):
    _, idmap, _ = build_players(info, "t1")
    csv = tmp_path / "events.csv"
    _events().to_csv(csv, index=False)
    ev = parse_events(csv, info, idmap, "t1").set_index("type")
    # a pass carries the xThreat of its targeted option; shots and engagements have none
    assert (ev.loc["pass", "xthreat"], ev.loc["pass", "dangerous"]) == (0.04, True)
    assert ev.loc[["goal", "pressure", "tackle", "foul"], "xthreat"].isna().all()
    assert list(ev.loc[["pressure", "tackle", "foul"], "subtype"]) == ["pressing", "counter_press", "other"]
    assert pd.isna(ev.loc["pass", "subtype"])                        # subtype only on engagements and runs
    assert (ev.loc["run", "speed_band"], ev.loc["goal", "lead_to_shot"]) == ("sprinting", True)
    assert (ev["phase"] == "build_up").all() and (ev["phase_against"] == "high_block").all()


def test_match_row_has_periods_teams_and_directions(info):
    _, idmap, spans = build_players(info, "t1")
    tracking, _, _ = parse_tracking(_frames(), info, idmap, spans, "t1")
    m = build_match(info, "t1", tracking).iloc[0]
    assert (m["p1_start_ts"], m["p1_end_ts"], m["p2_start_ts"], m["p2_end_ts"]) == (0, 3, 5, 8)
    assert (m["home_team"], m["away_team_short"], m["home_side_p2"]) == (
        "Home FC", "Away", "right_to_left")


def test_every_table_fits_its_schema(info, tmp_path):
    players, idmap, spans = build_players(info, "t1")
    tracking, ball, _ = parse_tracking(_frames(), info, idmap, spans, "t1")
    csv = tmp_path / "events.csv"
    _events().to_csv(csv, index=False)
    tables = {"players": players, "tracking": tracking, "ball": ball,
              "events": parse_events(csv, info, idmap, "t1"),
              "matches": build_match(info, "t1", tracking)}
    for name, df in tables.items():
        path = tmp_path / f"{name}.parquet"
        write_parquet(df, name, path)
        assert list(pd.read_parquet(path).columns) == [f.name for f in SCHEMAS[name]]