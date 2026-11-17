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
               "gold_pass_network", "gold_shots", "gold_player_5min", "gold_match_timeline", "gold_player_card",
               "gold_team_shape", "gold_pressing", "gold_team_build_up", "gold_player_fatigue", "gold_space_control",
               "gold_team_profile", "gold_events", "gold_match_library", "gold_replay_frames"]


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
            tracking.append(("mx", pid, team, 1, ts, 50.0, 34.0, speed, bool(speed and speed > 25), False, False,
                             ts != 1))
    events = [("mx-e1", 0, "H01", "H02", "HOME", "pass", 40.0, 30.0, 50.0, 30.0, "successful"),
              ("mx-e2", 1, "H01", None, "HOME", "shot", 90.0, 30.0, 105.0, 34.0, "shot"),
              ("mx-e3", 2, "H01", None, "HOME", "goal", 100.0, 34.0, 105.0, 34.0, "shot"),
              ("mx-e4", 2, "A01", None, "AWAY", "shot", 10.0, 34.0, 0.0, 34.0, "shot"),
              ("mx-r1", 1, "H03", None, "HOME", "run", 60.0, 30.0, 80.0, 20.0, "n/a")]
    i32 = {"ts": "int32", "period": "int32", "shirt_number": "int32", "start_ts": "int32", "end_ts": "int32"}
    frames = {
        "tracking": pd.DataFrame(tracking, columns=["match_id", "player_id", "team_id", "period", "ts", "x", "y",
                                                    "speed_kmh", "is_sprint", "was_corrected", "is_after_gap",
                                                    "is_detected"]),
        "events": pd.DataFrame(events, columns=["event_id", "ts", "player_id", "receiver_id", "team_id", "type",
                                                "x_start", "y_start", "x_end", "y_end", "outcome"]),
        "ball": pd.DataFrame({"match_id": "mx", "ts": [0, 1, 2], "period": 1, "x": 50.0, "y": 34.0, "z": 0.0,
                              "possession": ["HOME", None, "AWAY"]}),
        "players": pd.DataFrame([("mx", p, t, f"Name {p}", f"N. {p}", "CM", n + 1, 0, 2, 5000 + n)
                                 for n, (p, t) in enumerate(players)],
                                columns=["match_id", "player_id", "team_id", "name", "short_name", "position",
                                         "shirt_number", "start_ts", "end_ts", "source_player_id"]),
        "matches": pd.DataFrame([{"match_id": "mx", "competition": "Test", "season": "2026", "round": "1",
                                  "kickoff_utc": "2026-01-01T00:00:00Z", "stadium": "Park", "home_team": "Home FC",
                                  "away_team": "Away FC", "home_team_short": "Home", "away_team_short": "Away",
                                  "home_color": "#ff0000", "away_color": "#0000ff", "home_score": 1, "away_score": 0,
                                  "pitch_length": 105.0, "pitch_width": 68.0, "p1_start_ts": 0, "p1_end_ts": 1,
                                  "p2_start_ts": 2, "p2_end_ts": 2, "home_side_p1": "left_to_right",
                                  "home_side_p2": "right_to_left"}]),
    }
    frames["tracking"].insert(8, "speed_rejected", False)
    frames["events"].insert(0, "match_id", "mx")
    frames["events"]["period"] = 1
    ev = frames["events"]
    is_run = ev["type"] == "run"
    ev["phase"], ev["phase_against"], ev["speed_band"] = "create", "medium_block", "running"
    ev["xthreat"] = [0.05 if t == "pass" else 0.1 if t == "run" else None for t in ev["type"]]
    ev["dangerous"] = pd.array([False if t in ("pass", "run") else None for t in ev["type"]], dtype="boolean")
    ev["subtype"] = ["behind" if r else None for r in is_run]
    ev["lead_to_shot"] = ev["type"].isin(["shot", "goal"])
    ev["targeted"] = pd.array([True if r else None for r in is_run], dtype="boolean")
    ev["received"] = pd.array([False if r else None for r in is_run], dtype="boolean")
    frames["events"] = ev[["match_id", "event_id", "ts", "period", "player_id", "receiver_id", "team_id", "type",
                           "x_start", "y_start", "x_end", "y_end", "outcome", "phase", "phase_against", "xthreat",
                           "dangerous", "speed_band", "subtype", "lead_to_shot", "targeted", "received"]]
    for df in frames.values():
        for col, typ in i32.items():
            if col in df:
                df[col] = df[col].astype(typ)
    frames["matches"]["home_score"] = frames["matches"]["home_score"].astype("int32")
    frames["matches"]["away_score"] = frames["matches"]["away_score"].astype("int32")
    for col in ("p1_start_ts", "p1_end_ts", "p2_start_ts", "p2_end_ts"):
        frames["matches"][col] = frames["matches"][col].astype("int32")
    return frames


REPLAY = "m001-20261117T120000Z"


def write_silver(root: Path, frames: dict) -> None:
    for name, df in frames.items():
        (root / name).mkdir(parents=True)
        out = df if "replay_id" in df else df.assign(replay_id=REPLAY)     # Silver says which replay it read
        out.to_parquet(root / name / "part-0.parquet", index=False)


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
    assert "WHY  every existing second has exactly 22 players" in proc.stdout     # the console says why too
    assert "players=23" in proc.stdout
    # the result file says WHY: how many rows and which ones
    checks = {c["name"]: c for c in json.loads((tmp_path / "out" / "silver.json").read_text())["checks"]}
    assert "1 failing row(s)" in checks["every existing second has exactly 22 players"]["detail"]
    assert "players=23" in checks["every existing second has exactly 22 players"]["detail"]
    assert checks["tracking is not empty"]["detail"] == ""            # a passing check has no detail


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
    checks = {c["name"]: c for c in json.loads((tmp_path / "out" / "silver.json").read_text())["checks"]}
    assert "ts" in checks["tracking follows the data contract"]["detail"]          # which column, expected and actual type
    assert "expected(INTEGER)" in checks["tracking follows the data contract"]["detail"]
    assert "kafka_offset" in checks["players follow the data contract"]["detail"]


@needs_soda
def test_a_match_built_from_two_replays_is_caught(tmp_path):
    frames = silver_tables()
    t = frames["tracking"]
    frames["tracking"] = t.assign(replay_id=[REPLAY if i % 2 else "m001-20261117T130000Z" for i in range(len(t))])
    names = failed_names(run_silver(tmp_path, frames))
    assert "tracking holds one replay per match" in names
    assert "events holds one replay per match" not in names


@needs_soda
def test_the_replay_id_of_bronze_never_reaches_silver(tmp_path):
    frames = silver_tables()
    for table in frames:
        frames[table]["kafka_replay_id"] = "m001-20261116T101503Z"
    proc = run_silver(tmp_path, frames)
    checks = {c["name"]: c for c in json.loads((tmp_path / "out" / "silver.json").read_text())["checks"]}
    contract = {name: c for name, c in checks.items() if name.endswith("the data contract")}
    assert len(contract) == 5
    for name, check in contract.items():
        assert check["outcome"] == "fail", name
        assert "kafka_replay_id" in check["detail"], name
    assert proc.returncode != 0


@needs_soda
def test_a_bad_possession_a_run_with_a_receiver_and_a_missing_source_id_are_caught(tmp_path):
    frames = silver_tables()
    frames["ball"].loc[1, "possession"] = "BOTH"
    frames["events"].loc[frames["events"]["type"] == "run", "receiver_id"] = "H01"
    frames["players"]["source_player_id"] = frames["players"]["source_player_id"].astype("Int64")
    frames["players"].loc[0, "source_player_id"] = None
    names = failed_names(run_silver(tmp_path, frames))
    assert "ball possession is HOME, AWAY or null" in names
    assert "run fields are set on runs only, and every run says if it was targeted and received" in names
    assert any("source_player_id" in n for n in names)


@needs_soda
def test_the_silver_demo_catches_its_own_damage_and_exits_zero(tmp_path):
    proc = run_silver(tmp_path, silver_tables(), "--demo-failure")
    assert proc.returncode == 0, proc.stdout[-2500:]
    assert "the checks work" in proc.stdout
    assert not (tmp_path / "out" / "silver.json").exists()   # a demo never replaces the result of a real run


@needs_soda
def test_injected_damage_fails_like_a_real_run_without_replacing_its_result(tmp_path):
    proc = run_silver(tmp_path, silver_tables(), "--inject-damage")
    assert proc.returncode == 1, proc.stdout[-2500:]
    result = json.loads((tmp_path / "out" / "silver-damaged.json").read_text())
    assert result["failed"] > 0
    assert not (tmp_path / "out" / "silver.json").exists()


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
            [("mx", "H01", "HOME", 0, 1, "0-5", 0, 300, 300, 3, 0.01, 5.6, 1, 26.0, 1, 1, 1, 0, 0, 0),
             ("mx", "A01", "AWAY", 0, 1, "0-5", 0, 300, 300, 3, 0.01, 5.0, 0, 10.0, 0, 1, 0, 0, 0, 0)],
            ["match_id", "player_id", "team_id", "window_index", "period", "window_label", "window_start_ts",
             "window_end_ts", "window_seconds", "tracked_seconds", "coverage", "distance_m", "sprint_seconds",
             "max_speed_kmh", "passes", "shots", "goals", "tackles", "fouls", "pressures"],
            ints=["window_index", "period", "window_start_ts", "window_end_ts", "window_seconds"],
            bigs=["tracked_seconds", "sprint_seconds", "passes", "shots", "goals", "tackles", "fouls", "pressures"]),
    }
    tables.update(matchlens_tables())
    if mutate:
        mutate(tables)
    con = duckdb.connect(str(path))
    for name, frame in tables.items():
        con.register("frame", frame)
        con.execute(f"create table {name} as select * from frame")
        con.unregister("frame")
    con.close()


def typed(rows: list[dict], types: dict) -> pd.DataFrame:
    d = pd.DataFrame(rows)
    return d.astype({c: t for c, t in types.items() if c in d})


def matchlens_tables() -> dict:
    """Healthy rows of the MatchLens tables, consistent with the six tables above (HOME 1-0, one HOME pass)."""
    i32, i64, f64 = "int32", "int64", "float64"
    window = {"window_index": i32, "period": i32, "window_start_ts": i32, "window_end_ts": i32, "window_seconds": i64}
    timeline = typed([
        dict(match_id="mx", team_id=t, window_index=0, period=1, window_label="0-5", window_start_ts=0, window_end_ts=300,
             window_seconds=300, passes=p, final_third_passes=0,
             field_tilt=None, possession_seconds=1, known_seconds=2, possession_share=0.5, possession_greyed=True,
             shots=1, goals=g, defensive_actions=0, xthreat_successful_passes=x, score_home_end=1, score_away_end=0)
        for t, p, g, x in (("HOME", 1, 1, 0.05), ("AWAY", 0, 0, 0.0))],
        {**window, "passes": i64, "final_third_passes": i64, "field_tilt": f64, "possession_seconds": i64,
         "known_seconds": i64, "shots": i64, "goals": i64, "defensive_actions": i64, "score_home_end": i32,
         "score_away_end": i32})
    card = typed([
        dict(match_id="mx", player_id=pid, team_id=t, source_player_id=src, name=n, short_name=sn, position=pos,
             shirt_number=sh, opponent_name=opp, is_outfield=True, tracked_minutes=0.1, is_eligible=False, dpm=dpm,
             top_speed_kmh=top, sprint_count=spr, sprints_per_min=spr * 20.0, passes_successful=ps,
             passes_successful_per_min=ps * 20.0, progressive_passes=ps, progressive_passes_successful=ps,
             progressive_passes_successful_per_min=ps * 20.0, defensive_actions=0, defensive_actions_per_min=0.0,
             goals=g, passes_received_successful=0, score_work_rate=None, score_sprints=None, score_passing=None,
             score_progression=None, score_defending=None, involvement=inv, is_hub=hub)
        for pid, t, src, n, sn, pos, sh, opp, dpm, top, spr, ps, g, inv, hub in (
            ("H01", "HOME", 5000, "Hugo", "H.", "CM", 8, "Away FC", 120.0, 26.0, 1, 1, 1, 0.5, True),
            ("A01", "AWAY", 5011, "Alex", "A.", "ST", 9, "Home FC", 110.0, 10.0, 0, 0, 0, None, False))],
        {"source_player_id": i64, "shirt_number": i32, "sprint_count": i64, "passes_successful": i64,
         "progressive_passes": i64, "progressive_passes_successful": i64, "defensive_actions": i64, "goals": i64,
         "passes_received_successful": i64, "involvement": f64, **{f"score_{s}": "Int32" for s in
         ("work_rate", "sprints", "passing", "progression", "defending")}})
    shape = typed([dict(match_id="mx", team_id=t, phase=ph, seconds_used=1, width=30.0, length=25.0, area=750.0,
                        defensive_line_height=35.0, detected_share=0.6)
                   for t in ("HOME", "AWAY") for ph in ("in_possession", "out_of_possession", "unknown")],
                  {"seconds_used": i64})
    pressing = typed([
        dict(match_id="mx", team_id=t, window_index=0, period=1, window_label="0-15", window_start_ts=0, window_end_ts=900,
             window_seconds=900, defensive_actions=0,
             opponent_passes=op, ppp=ppp, ppp_greyed=op < 10, defensive_actions_own_third=0,
             defensive_actions_middle_third=0,
             defensive_actions_final_third=0, high_press_share=None)
        for t, op, ppp in (("HOME", 0, None), ("AWAY", 1, 0.0))],
        {**window, "defensive_actions": i64, "opponent_passes": i64, "ppp": f64, "high_press_share": f64,
         **{f"defensive_actions_{z}_third": i64 for z in ("own", "middle", "final")}})
    build_up = typed([
        dict(match_id="mx", team_id=t, progressive_passes=n, progressive_passes_successful=n,
             tracked_minutes=0.05, progressive_passes_per90=n * 1800.0,
             final_third_entries=0, entries_left=0, entries_centre=0, entries_right=0, share_left=None,
             share_centre=None, share_right=None)
        for t, n in (("HOME", 1), ("AWAY", 0))],
        {"progressive_passes": i64, "progressive_passes_successful": i64,
         "final_third_entries": i64, "entries_left": i64, "entries_centre": i64, "entries_right": i64,
         "share_left": f64, "share_centre": f64, "share_right": f64})
    fatigue = typed([
        dict(match_id="mx", player_id=pid, team_id=t, short_name=sn, position=pos, start_ts=0, end_ts=2, is_outfield=True,
             minutes_on_pitch=0.0, dpm_first15=100.0, dpm_last5=90.0, drop=0.1, tracked_minutes_first15=0.05,
             tracked_minutes_last5=0.05, is_eligible=False)
        for pid, t, sn, pos in (("H01", "HOME", "H.", "CM"), ("A01", "AWAY", "A.", "ST"))],
        {"start_ts": i32, "end_ts": i32})
    space = typed([
        dict(match_id="mx", team_id=t, window_index=0, period=1, window_label="0-5", window_start_ts=0, window_end_ts=300,
             window_seconds=300, seconds_used=3,
             space_share=s, seconds_in_possession=1, space_share_in_possession=s_in, seconds_out_of_possession=1,
             space_share_out_of_possession=s_out, seconds_unknown=1, space_share_unknown=s, detected_share=0.67)
        for t, s, s_in, s_out in (("HOME", 0.55, 0.6, 0.5), ("AWAY", 0.45, 0.5, 0.4))],
        {**window, "seconds_used": i64, "seconds_in_possession": i64, "seconds_out_of_possession": i64,
         "seconds_unknown": i64})
    profile = typed([
        dict(match_id="mx", team_id=t, team_name=n, opponent_name=o, possession_share=0.5, field_tilt=0.5,
             shots_and_goals=sg, width=30.0, length=25.0, defensive_line_height=35.0, ppp=ppp, high_press_share=None,
             progressive_passes=pp, progressive_passes_per90=pp * 1800.0, dpm_outfield=dpm, share_left=None,
             share_centre=None, share_right=None, gap_possession_share=0.0, gap_field_tilt=0.0, gap_shots_and_goals=gs,
             gap_progressive_passes=gp, gap_ppp=None, gap_dpm_outfield=gd)
        for t, n, o, sg, ppp, pp, dpm, gs, gp, gd in (
            ("HOME", "Home FC", "Away FC", 2, None, 1, 120.0, 0.6667, 2.0, 0.087),
            ("AWAY", "Away FC", "Home FC", 1, 0.0, 0, 110.0, -0.6667, -2.0, -0.087))],
        {"shots_and_goals": i64, "progressive_passes": i64, "ppp": f64, "high_press_share": f64, "share_left": f64,
         "share_centre": f64, "share_right": f64, "gap_ppp": f64})
    events = typed([
        dict(match_id="mx", event_id=e, ts=ts, period=1, player_id=pid, receiver_id=rec, team_id=t, type=ty,
             x_start=xs, y_start=ys, x_end=xe, y_end=ye, outcome=out, phase="create", phase_against="medium_block",
             xthreat=xt, dangerous=None, speed_band="running", subtype=sub, lead_to_shot=False, targeted=tg, received=rv,
             x_att_start=xs if t == "HOME" else 105 - xs, y_att_start=ys if t == "HOME" else 68 - ys,
             x_att_end=xe if t == "HOME" else 105 - xe, y_att_end=ye if t == "HOME" else 68 - ye,
             player_short_name=f"N. {pid}", shirt_number=8, receiver_short_name=f"N. {rec}" if rec else None,
             third=third, lane="centre", goal_ts=ts + 1 if ty == "goal" else None,
             goal_ts_method="ball_in_goal" if ty == "goal" else None)
        for e, ts, pid, rec, t, ty, xs, ys, xe, ye, out, xt, sub, tg, rv, third in (
            ("mx-e1", 0, "H01", "H02", "HOME", "pass", 40.0, 30.0, 50.0, 30.0, "successful", 0.05, None, None, None, "middle"),
            ("mx-e2", 1, "H01", None, "HOME", "shot", 90.0, 30.0, 105.0, 34.0, "shot", None, None, None, None, "final"),
            ("mx-e3", 2, "H01", None, "HOME", "goal", 100.0, 34.0, 105.0, 34.0, "shot", None, None, None, None, "final"),
            ("mx-e4", 2, "A01", None, "AWAY", "shot", 10.0, 34.0, 0.0, 34.0, "shot", None, None, None, None, "final"),
            ("mx-r1", 1, "H03", None, "HOME", "run", 60.0, 30.0, 80.0, 20.0, "n/a", 0.1, "behind", True, False, "middle"))],
        {"ts": i32, "period": i32, "shirt_number": i32, "xthreat": f64, "dangerous": "boolean", "targeted": "boolean",
         "received": "boolean", "goal_ts": "Int32"})
    library = typed([dict(match_id="mx", home_team="Home FC", away_team="Away FC", home_team_short="Home",
                          away_team_short="Away", home_color="#ff0000", away_color="#0000ff", home_score=1, away_score=0,
                          kickoff_utc="2026-01-01T00:00:00Z", match_date=pd.Timestamp("2026-01-01").date(),
                          competition="Test", season="2026", round="1", stadium="Park", p1_start_ts=0,
                          p1_end_ts=1, p2_start_ts=2, p2_end_ts=2, speeds_rejected=0, match_seconds=3,
                          tracked_seconds=3, tracked_share=1.0)],
                    {"home_score": i32, "away_score": i32, "match_seconds": i32, "tracked_seconds": i64,
                     "speeds_rejected": i64,
                     **{c: i32 for c in ("p1_start_ts", "p1_end_ts", "p2_start_ts", "p2_end_ts")}})
    frames = typed([dict(match_id="mx", ts=ts, period=1 if ts < 2 else 2, object_id=oid, object_type=kind,
                         team_id=team, shirt_number=n, position=("GK" if n == 1 else "CM") if team else None,
                         x=x, y=34.0, z=None if team else 0.2, speed_kmh=None, is_detected=True if team else None,
                         possession="HOME", home_space_share=0.55)
                    for ts in range(3)
                    for oid, kind, team, n, x in [*((f"{t[0]}{n:02d}", "player", t, n, 5.0 * n) for t in ("HOME", "AWAY")
                                                    for n in range(1, 12)), ("ball", "ball", None, None, 107.0)]],
                   {"ts": i32, "period": i32, "shirt_number": "Int32", "speed_kmh": f64, "is_detected": "boolean",
                    "z": f64})
    return {"gold_match_library": library, "gold_match_timeline": timeline, "gold_player_card": card, "gold_team_shape": shape,
            "gold_pressing": pressing, "gold_team_build_up": build_up, "gold_player_fatigue": fatigue,
            "gold_space_control": space, "gold_team_profile": profile, "gold_events": events,
            "gold_replay_frames": frames}


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
def test_a_gold_column_with_a_stale_type_is_explained(tmp_path):
    """The case seen on a real run: Gold built before attacking_goal_x became DOUBLE."""
    def stale(t):
        t["gold_shots"]["attacking_goal_x"] = t["gold_shots"]["attacking_goal_x"].astype("float32")
    proc = run_gold(tmp_path, mutate=stale)
    assert "gold_shots follows the data contract" in failed_names(proc)
    checks = {c["name"]: c for c in json.loads((tmp_path / "out" / "gold.json").read_text())["checks"]}
    assert "attacking_goal_x" in checks["gold_shots follows the data contract"]["detail"]


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
def test_gold_matchlens_rules_are_enforced(tmp_path):
    def damage(t):
        t["gold_pressing"].loc[0, "defensive_actions"] = 1                    # a run counted as a defensive action
        t["gold_space_control"].loc[0, "space_share"] = 0.7                  # HOME + AWAY no longer cover the pitch
        t["gold_player_card"].loc[0, "score_passing"] = 80                   # a score for an ineligible player
        t["gold_match_timeline"].loc[0, "possession_greyed"] = False         # 2 known seconds shown as reliable
        t["gold_replay_frames"] = t["gold_replay_frames"].iloc[1:]            # a player missing from second 0
    names = failed_names(run_gold(tmp_path, mutate=damage))
    assert "defensive actions are pressures, tackles and fouls, never runs" in names
    assert "the two teams share the pitch (HOME + AWAY = 1 in every window)" in names
    assert "an eligible player has 5 scores between 0 and 100, the others none" in names
    assert "a window is greyed exactly when it has fewer than 60 known seconds" in names
    assert "every tracked second has its ball and 22 players" in names


@needs_soda
def test_gold_demo_exits_zero(tmp_path):
    proc = run_gold(tmp_path, "--demo-failure")
    assert proc.returncode == 0, proc.stdout[-2500:]
    assert "the checks work" in proc.stdout
