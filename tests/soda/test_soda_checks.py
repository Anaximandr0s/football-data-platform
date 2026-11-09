"""Soda checks (soda/checks/*.yml) on tiny hand-made Silver and Gold data: no Docker, no MinIO.

Each test runs soda/run_checks.py as a subprocess, like `make soda`. Needs Soda Core 3.5 and DuckDB 2.0 installed
as in soda/Dockerfile (the Soda connector is installed with --no-deps because it pins DuckDB 1.0): skipped otherwise.
The file-structure test needs only PyYAML.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "soda" / "run_checks.py"
CHECKS = ROOT / "soda" / "checks"
SILVER_TABLES = ["tracking", "events", "ball", "players", "matches"]
GOLD_TABLES = ["gold_player_match_stats", "gold_team_match_stats", "gold_zone_occupancy",
               "gold_pass_network", "gold_shots", "gold_player_5min"]


def test_every_table_has_a_checks_block_with_a_schema_check():
    yaml = pytest.importorskip("yaml")
    for layer, tables in (("silver", [f"silver_{t}" for t in SILVER_TABLES]), ("gold", GOLD_TABLES)):
        doc = yaml.safe_load((CHECKS / f"{layer}.yml").read_text(encoding="utf-8"))
        assert sorted(k.removeprefix("checks for ") for k in doc) == sorted(tables)
        for table in tables:
            checks = doc[f"checks for {table}"]
            assert any(isinstance(c, dict) and "schema" in c for c in checks), f"{table} has no schema check"


# ------------------------------------------------------------------ the checks themselves (need soda + duckdb 2)
def _has_soda() -> bool:
    try:
        return importlib.util.find_spec("soda.scan") is not None and importlib.util.find_spec("duckdb") is not None
    except ModuleNotFoundError:
        return False


needs_soda = pytest.mark.skipif(not _has_soda(), reason="Soda Core 3.5 + DuckDB 2.0 not installed (see soda/Dockerfile)")


def silver_tables() -> dict:
    """A healthy mini Silver: 22 players (11 per team), 3 seconds, a pass, two HOME shots (one goal), one AWAY shot."""
    players = [(f"{p}{i:02d}", t) for p, t in (("H", "HOME"), ("A", "AWAY")) for i in range(1, 12)]
    tracking = []
    for pid, team in players:
        for ts, speed in ((0, None), (1, 10.0), (2, 26.0)):
            tracking.append(("mx", pid, team, 1, ts, 50.0, 34.0, speed, bool(speed and speed > 25), False, False))
    events = [("mx-e1", 0, "H01", "H02", "HOME", "pass", 40.0, 30.0, 50.0, 30.0, "successful"),
              ("mx-e2", 1, "H01", None, "HOME", "shot", 90.0, 30.0, 105.0, 34.0, "shot"),
              ("mx-e3", 2, "H01", None, "HOME", "goal", 100.0, 34.0, 105.0, 34.0, "shot"),
              ("mx-e4", 2, "A01", None, "AWAY", "shot", 10.0, 34.0, 0.0, 34.0, "shot")]
    i32 = {"ts": "int32", "period": "int32", "shirt_number": "int32", "start_ts": "int32", "end_ts": "int32"}
    frames = {
        "tracking": pd.DataFrame(tracking, columns=["match_id", "player_id", "team_id", "period", "ts", "x", "y",
                                                    "speed_kmh", "is_sprint", "was_corrected", "is_after_gap"]),
        "events": pd.DataFrame(events, columns=["event_id", "ts", "player_id", "receiver_id", "team_id", "type",
                                                "x_start", "y_start", "x_end", "y_end", "outcome"]),
        "ball": pd.DataFrame({"match_id": "mx", "ts": [0, 1, 2], "period": 1, "x": 50.0, "y": 34.0, "z": 0.0}),
        "players": pd.DataFrame([("mx", p, t, f"Name {p}", f"N. {p}", "CM", n + 1, 0, 2)
                                 for n, (p, t) in enumerate(players)],
                                columns=["match_id", "player_id", "team_id", "name", "short_name", "position",
                                         "shirt_number", "start_ts", "end_ts"]),
        "matches": pd.DataFrame([{"match_id": "mx", "competition": "Test", "season": "2026", "round": "1",
                                  "kickoff_utc": "2026-01-01T00:00:00Z", "stadium": "Park", "home_team": "Home FC",
                                  "away_team": "Away FC", "home_team_short": "Home", "away_team_short": "Away",
                                  "home_color": "#ff0000", "away_color": "#0000ff", "home_score": 1, "away_score": 0,
                                  "pitch_length": 105.0, "pitch_width": 68.0, "p1_start_ts": 0, "p1_end_ts": 1,
                                  "p2_start_ts": 2, "p2_end_ts": 2, "home_side_p1": "left_to_right",
                                  "home_side_p2": "right_to_left"}]),
    }
    frames["events"].insert(0, "match_id", "mx")
    frames["events"]["period"] = 1
    frames["events"] = frames["events"][["match_id", "event_id", "ts", "period", "player_id", "receiver_id", "team_id",
                                         "type", "x_start", "y_start", "x_end", "y_end", "outcome"]]
    for df in frames.values():
        for col, typ in i32.items():
            if col in df:
                df[col] = df[col].astype(typ)
    frames["matches"]["home_score"] = frames["matches"]["home_score"].astype("int32")
    frames["matches"]["away_score"] = frames["matches"]["away_score"].astype("int32")
    for col in ("p1_start_ts", "p1_end_ts", "p2_start_ts", "p2_end_ts"):
        frames["matches"][col] = frames["matches"][col].astype("int32")
    return frames


def write_silver(root: Path, frames: dict) -> None:
    for name, df in frames.items():
        (root / name).mkdir(parents=True)
        df.to_parquet(root / name / "part-0.parquet", index=False)


def run(tmp: Path, *args: str):
    cmd = [sys.executable, str(RUNNER), *args, "--out", str(tmp / "out")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=240)


def run_silver(tmp: Path, frames: dict, *extra: str):
    root = tmp / "silver"
    write_silver(root, frames)
    return run(tmp, "--layer", "silver", "--silver-reader", "parquet", "--silver-parquet-root", str(root), *extra)


def failed_names(proc) -> list[str]:
    return [line.split("INFO   |")[-1].strip().removesuffix("[FAILED]").strip()
            for line in proc.stdout.splitlines() if line.rstrip().endswith("[FAILED]")]


@needs_soda
def test_healthy_silver_passes_and_writes_the_result_file(tmp_path):
    proc = run_silver(tmp_path, silver_tables())
    assert proc.returncode == 0, proc.stdout[-2500:]
    result = json.loads((tmp_path / "out" / "silver.json").read_text())
    assert result["layer"] == "silver" and result["failed"] == 0 and result["errors"] == 0 and result["passed"] > 50


@needs_soda
def test_a_duplicated_tracking_row_is_caught(tmp_path):
    frames = silver_tables()
    frames["tracking"] = pd.concat([frames["tracking"], frames["tracking"].iloc[[0]]], ignore_index=True)
    proc = run_silver(tmp_path, frames)
    assert proc.returncode == 1
    assert "tracking has one row per (match_id, player_id, ts)" in failed_names(proc)
    assert "every existing second has exactly 22 players" in failed_names(proc)


@needs_soda
def test_a_position_off_the_pitch_and_a_speed_over_40_are_caught(tmp_path):
    frames = silver_tables()
    frames["tracking"].loc[0, ["x", "speed_kmh"]] = [120.0, 55.0]
    names = failed_names(run_silver(tmp_path, frames))
    assert "positions are inside the 105 x 68 pitch" in names
    assert "speed is at most 40 km/h (null allowed)" in names


@needs_soda
def test_a_missing_team_and_a_unknown_player_are_caught(tmp_path):
    frames = silver_tables()
    frames["tracking"].loc[0, "team_id"] = None
    frames["tracking"].loc[1, "player_id"] = "Z99"
    names = failed_names(run_silver(tmp_path, frames))
    assert "every tracking row has a team" in names
    assert "every tracked player exists in silver_players with the same team" in names


@needs_soda
def test_events_with_the_wrong_orientation_or_wrong_goal_count_are_caught(tmp_path):
    frames = silver_tables()
    frames["events"].loc[frames["events"]["team_id"] == "HOME", "x_start"] = 10.0   # HOME shots toward its own goal
    frames["matches"]["home_score"] = frames["matches"]["home_score"].astype("int32") + 1
    names = failed_names(run_silver(tmp_path, frames))
    assert "events are oriented per team (HOME shots toward x = 105, AWAY shots toward x = 0)" in names
    assert "goals in events equal home_score + away_score of the match" in names


@needs_soda
def test_a_wrong_column_type_or_a_kafka_column_breaks_the_contract(tmp_path):
    frames = silver_tables()
    frames["tracking"]["ts"] = frames["tracking"]["ts"].astype("float64")
    frames["players"]["kafka_offset"] = 1
    names = failed_names(run_silver(tmp_path, frames))
    assert "tracking follows the data contract" in names and "players follow the data contract" in names


@needs_soda
def test_the_silver_demo_catches_its_own_damage_and_exits_zero(tmp_path):
    proc = run_silver(tmp_path, silver_tables(), "--demo-failure")
    assert proc.returncode == 0, proc.stdout[-2500:]
    assert "the checks work" in proc.stdout
    assert not (tmp_path / "out" / "silver.json").exists()   # a demo never replaces the result of a real run


# ------------------------------------------------------------------ Gold
def gold_db(path: Path, mutate=None) -> None:
    import duckdb

    def df(rows, cols, ints=(), bigs=()):
        d = pd.DataFrame(rows, columns=cols)
        for c in ints:
            d[c] = d[c].astype("int32")
        for c in bigs:
            d[c] = d[c].astype("int64")
        return d

    player_cols = ["match_id", "player_id", "team_id", "name", "short_name", "position", "shirt_number",
                   "minutes_on_pitch", "tracked_seconds", "distance_m", "distance_km", "sprint_seconds", "sprint_count",
                   "max_speed_kmh", "avg_speed_kmh", "avg_x", "avg_y", "passes", "passes_successful", "passes_received",
                   "shots", "goals", "tackles", "fouls", "pressures"]
    bigp = ["tracked_seconds", "sprint_seconds", "sprint_count", "passes", "passes_successful", "passes_received",
            "shots", "goals", "tackles", "fouls", "pressures"]
    tables = {
        "gold_player_match_stats": df(
            [("mx", "H01", "HOME", "Hugo", "H.", "CM", 8, 1.0, 3, 5.6, 0.006, 1, 1, 26.0, 12.0, 50.0, 34.0, 1, 1, 0, 1, 1, 0, 0, 0),
             ("mx", "A01", "AWAY", "Alex", "A.", "ST", 9, 1.0, 3, 5.0, 0.005, 0, 0, 10.0, 8.0, 50.0, 34.0, 0, 0, 0, 1, 0, 0, 0, 0)],
            player_cols, ints=["shirt_number"], bigs=bigp),
        "gold_team_match_stats": df(
            [("mx", "HOME", "Home FC", "Home", "#ff0000", 1, 0, 0.006, 1, 1, 26.0, 1, 1, 1.0, 1, 1, 0, 0, 0, 50.0, 34.0),
             ("mx", "AWAY", "Away FC", "Away", "#0000ff", 0, 1, 0.005, 0, 0, 10.0, 0, 0, None, 1, 0, 0, 0, 0, 50.0, 34.0)],
            ["match_id", "team_id", "team_name", "team_short", "team_color", "score", "opponent_score", "distance_km",
             "sprint_count", "sprint_seconds", "max_speed_kmh", "passes", "passes_successful", "pass_accuracy", "shots",
             "goals", "tackles", "fouls", "pressures", "avg_x", "avg_y"],
            ints=["score", "opponent_score"],
            bigs=["sprint_count", "sprint_seconds", "passes", "passes_successful", "shots", "goals", "tackles", "fouls",
                  "pressures"]),
        "gold_zone_occupancy": df(
            [("mx", "H01", "HOME", 14, 2, 2, 35.0, 52.5, 34.0, 51.0, 3, 1.0),
             ("mx", "A01", "AWAY", 15, 3, 2, 52.5, 70.0, 34.0, 51.0, 3, 1.0)],
            ["match_id", "player_id", "team_id", "zone_id", "zone_x", "zone_y", "x_min", "x_max", "y_min", "y_max",
             "seconds", "share_of_tracked_seconds"], ints=["zone_id", "zone_x", "zone_y"], bigs=["seconds"]),
        "gold_pass_network": df(
            [("mx", "H01", "H02", "HOME", "H.", "H2.", 1, 1, 40.0, 30.0, 50.0, 30.0)],
            ["match_id", "passer_id", "receiver_id", "team_id", "passer_name", "receiver_name", "passes",
             "passes_successful", "avg_start_x", "avg_start_y", "avg_end_x", "avg_end_y"],
            bigs=["passes", "passes_successful"]),
        "gold_shots": df(
            [("mx", "mx-e2", 1, 1, "H01", "Hugo", "H.", 8, "HOME", "shot", False, 90.0, 30.0, 105.0, 34.0, 105.0, 15.5, 0, 0),
             ("mx", "mx-e3", 2, 1, "H01", "Hugo", "H.", 8, "HOME", "goal", True, 100.0, 34.0, 105.0, 34.0, 105.0, 5.0, 1, 0),
             ("mx", "mx-e4", 2, 1, "A01", "Alex", "A.", 9, "AWAY", "shot", False, 10.0, 34.0, 0.0, 34.0, 0.0, 10.0, 1, 0)],
            ["match_id", "event_id", "ts", "period", "player_id", "player_name", "player_short_name", "shirt_number",
             "team_id", "type", "is_goal", "x_start", "y_start", "x_end", "y_end", "attacking_goal_x",
             "distance_to_goal_m", "score_home_after", "score_away_after"],
            ints=["ts", "period", "shirt_number", "score_home_after", "score_away_after"]),
        "gold_player_5min": df(
            [("mx", "H01", "HOME", 0, 300, 3, 0.01, 5.6, 1, 26.0, 1, 1, 1, 0, 0, 0),
             ("mx", "A01", "AWAY", 0, 300, 3, 0.01, 5.0, 0, 10.0, 0, 1, 0, 0, 0, 0)],
            ["match_id", "player_id", "team_id", "window_start_ts", "window_end_ts", "tracked_seconds", "coverage",
             "distance_m", "sprint_seconds", "max_speed_kmh", "passes", "shots", "goals", "tackles", "fouls", "pressures"],
            ints=["window_start_ts", "window_end_ts"],
            bigs=["tracked_seconds", "sprint_seconds", "passes", "shots", "goals", "tackles", "fouls", "pressures"]),
    }
    if mutate:
        mutate(tables)
    con = duckdb.connect(str(path))
    for name, frame in tables.items():
        con.register("frame", frame)
        con.execute(f"create table {name} as select * from frame")
        con.unregister("frame")
    con.close()


def run_gold(tmp: Path, *extra: str, mutate=None):
    db = tmp / "football.duckdb"
    gold_db(db, mutate)
    return run(tmp, "--layer", "gold", "--gold-db", str(db), *extra)


@needs_soda
def test_healthy_gold_passes(tmp_path):
    proc = run_gold(tmp_path)
    assert proc.returncode == 0, proc.stdout[-2500:]
    assert json.loads((tmp_path / "out" / "gold.json").read_text())["failed"] == 0


@needs_soda
def test_gold_goal_count_not_matching_the_score_is_caught(tmp_path):
    def drop_goal(t):
        t["gold_shots"] = t["gold_shots"][t["gold_shots"]["type"] != "goal"]
    names = failed_names(run_gold(tmp_path, mutate=drop_goal))
    assert "goals in gold_shots equal the score in gold_team_match_stats" in names


@needs_soda
def test_gold_impossible_values_are_caught(tmp_path):
    def damage(t):
        t["gold_player_match_stats"].loc[0, ["distance_m", "max_speed_kmh", "sprint_count"]] = [-5.0, 55.0, 9]
        t["gold_zone_occupancy"].loc[0, "share_of_tracked_seconds"] = 0.4
    names = failed_names(run_gold(tmp_path, mutate=damage))
    assert "no negative distance" in names and "no speed above 40 km/h" in names
    assert "sprint efforts never exceed sprint seconds" in names
    assert "the zone shares of a player add up to 1" in names


@needs_soda
def test_gold_demo_exits_zero(tmp_path):
    proc = run_gold(tmp_path, "--demo-failure")
    assert proc.returncode == 0, proc.stdout[-2500:]
    assert "the checks work" in proc.stdout
