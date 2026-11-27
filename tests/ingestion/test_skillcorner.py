"""Tests of skillcorner.py on a tiny hand-made match: no Docker, no download.

    make test        (or: python -m pytest -q)
"""

import pandas as pd
import pytest

from ingestion.config import PITCH_L
from ingestion.schemas import SCHEMAS, write_parquet
from ingestion.skillcorner import build_match, build_players, parse_events, parse_tracking
from tests.ingestion.tiny_match import _events, _frames


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