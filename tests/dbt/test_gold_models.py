"""Gold models on a tiny hand-made Silver (Parquet files): no Docker, no MinIO, no Spark.

dbt runs for real (target dev, silver_reader=parquet) and the resulting DuckDB tables are checked.
Silver data of match m1: 4 players (H01, H02 HOME; A01, A02 AWAY), 9 events, final score 1-0.
Skipped when dbt or duckdb is not installed.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pd = pytest.importorskip("pandas")
DBT = shutil.which("dbt")
pytestmark = pytest.mark.skipif(DBT is None, reason="dbt is not installed")

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"
M = "m1"


def _tracking():
    rows = []

    def add(pid, team, series):
        for ts, speed, x, y in series:
            rows.append((M, pid, team, 1, ts, x, y, speed, bool(speed and speed > 25), False, False))

    # H01: speeds 10,30,30,10,26 then a gap, 27,27, a gap, 28. Positions chosen to hit zone edges.
    h01 = [(0, None, 0.0, 0.0), (1, 10.0, 104.9, 67.9), (2, 30.0, 105.0, 68.0), (3, 30.0, 50.0, 34.0),
           (4, 10.0, 50.0, 34.0), (5, 26.0, 50.0, 34.0), (8, None, 50.0, 34.0), (9, 27.0, 50.0, 34.0),
           (10, 27.0, 50.0, 34.0), (12, 28.0, 50.0, 34.0)]
    add("H01", "HOME", h01)
    add("H02", "HOME", [(0, None, 20.0, 10.0), (1, 5.0, 20.0, 10.0), (2, 5.0, 20.0, 10.0)])
    add("A01", "AWAY", [(0, None, 80.0, 30.0), (1, 8.0, 80.0, 30.0)])
    add("A02", "AWAY", [(0, None, 70.0, 50.0), (1, 8.0, 70.0, 50.0)])
    cols = ["match_id", "player_id", "team_id", "period", "ts", "x", "y", "speed_kmh",
            "is_sprint", "was_corrected", "is_after_gap"]
    return pd.DataFrame(rows, columns=cols)


def _events():
    e = [("e1", 1, "H01", "H02", "HOME", "pass", 40, 30, 50, 30, "successful"),
         ("e2", 2, "H01", "H02", "HOME", "pass", 40, 30, 50, 30, "unsuccessful"),
         ("e3", 3, "H02", "H01", "HOME", "pass", 50, 30, 40, 30, "successful"),
         ("e4", 4, "H01", None, "HOME", "shot", 90, 30, 105, 34, "shot"),
         ("e5", 5, "H01", None, "HOME", "goal", 100, 34, 105, 34, "shot"),
         ("e6", 6, "A01", None, "AWAY", "shot", 10, 34, 0, 34, "shot"),
         ("e7", 7, "A02", None, "AWAY", "pressure", 60, 30, 60, 30, "n/a"),
         ("e8", 7, "H02", None, "HOME", "tackle", 55, 30, 55, 30, "direct_regain"),
         ("e9", 8, "A01", None, "AWAY", "foul", 50, 30, 50, 30, "foul_committed")]
    cols = ["event_id", "ts", "player_id", "receiver_id", "team_id", "type",
            "x_start", "y_start", "x_end", "y_end", "outcome"]
    df = pd.DataFrame(e, columns=cols)
    df.insert(0, "match_id", M)
    df["period"] = 1
    return df


def _players():
    rows = [(M, "H01", "HOME", "Hugo One", "H. One", "CM", 8), (M, "H02", "HOME", "Hector Two", "H. Two", "CB", 4),
            (M, "A01", "AWAY", "Alex One", "A. One", "ST", 9), (M, "A02", "AWAY", "Adam Two", "A. Two", "CB", 5)]
    df = pd.DataFrame(rows, columns=["match_id", "player_id", "team_id", "name", "short_name", "position",
                                     "shirt_number"])
    df["start_ts"], df["end_ts"] = 0, 600
    return df


def _matches(home_score=1):
    return pd.DataFrame([{
        "match_id": M, "competition": "Test League", "season": "2026", "round": "1", "kickoff_utc": "2026-01-01T00:00:00Z",
        "stadium": "Test Park", "home_team": "Home FC", "away_team": "Away FC", "home_team_short": "Home",
        "away_team_short": "Away", "home_color": "#ff0000", "away_color": "#0000ff", "home_score": home_score,
        "away_score": 0, "pitch_length": 105.0, "pitch_width": 68.0, "p1_start_ts": 0, "p1_end_ts": 100,
        "p2_start_ts": 101, "p2_end_ts": 200, "home_side_p1": "left_to_right", "home_side_p2": "right_to_left"}])


def _write_silver(root: Path, home_score=1):
    ball = pd.DataFrame({"match_id": [M], "ts": [0], "period": [1], "x": [52.5], "y": [34.0], "z": [0.0]})
    for name, df in (("tracking", _tracking()), ("events", _events()), ("players", _players()),
                     ("matches", _matches(home_score)), ("ball", ball)):
        (root / name).mkdir(parents=True)
        df.to_parquet(root / name / "part-0.parquet", index=False)


def _dbt(tmp: Path, silver: Path, *args: str):
    env = {**os.environ, "DBT_TARGET": "dev", "GOLD_DUCKDB_PATH": str(tmp / "gold.duckdb"),
           "DBT_PROFILES_DIR": str(DBT_DIR), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    vars_ = json.dumps({"silver_reader": "parquet", "silver_parquet_root": str(silver)})
    cmd = [DBT, *args, "--project-dir", str(DBT_DIR), "--vars", vars_,
           "--target-path", str(tmp / "target"), "--log-path", str(tmp / "logs")]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=240)


@pytest.fixture(scope="module")
def gold(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gold")
    silver = tmp / "silver"
    _write_silver(silver)
    run = _dbt(tmp, silver, "build")
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-1000:]
    con = duckdb.connect(str(tmp / "gold.duckdb"), read_only=True)
    yield con
    con.close()


def rows(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_player_distance_speed_and_sprints(gold):
    h = rows(gold, "select * from gold_player_match_stats where player_id = 'H01'")[0]
    assert h["tracked_seconds"] == 10
    assert h["distance_m"] == pytest.approx(188 / 3.6, abs=0.06)     # null speeds add nothing
    assert h["max_speed_kmh"] == 30.0
    assert h["sprint_seconds"] == 6
    # efforts: ts 2-3, ts 5, ts 9-10, ts 12 (a gap between 10 and 12 starts a new effort)
    assert h["sprint_count"] == 4
    assert h["minutes_on_pitch"] == 10.0
    assert h["name"] == "Hugo One" and h["team_id"] == "HOME"


def test_player_actions_and_received_passes(gold):
    p = {r["player_id"]: r for r in rows(gold, "select * from gold_player_match_stats")}
    assert (p["H01"]["passes"], p["H01"]["passes_successful"], p["H01"]["passes_received"]) == (2, 1, 1)
    assert (p["H01"]["shots"], p["H01"]["goals"]) == (1, 1)            # shots excludes goals
    assert (p["H02"]["passes"], p["H02"]["passes_received"], p["H02"]["tackles"]) == (1, 2, 1)
    assert (p["A01"]["shots"], p["A01"]["fouls"], p["A02"]["pressures"]) == (1, 1, 1)
    assert p["A01"]["passes"] == 0                                       # no event: zero, not null


def test_team_stats_use_the_match_row(gold):
    t = {r["team_id"]: r for r in rows(gold, "select * from gold_team_match_stats")}
    assert (t["HOME"]["team_name"], t["HOME"]["score"], t["HOME"]["opponent_score"]) == ("Home FC", 1, 0)
    assert (t["AWAY"]["team_short"], t["AWAY"]["score"], t["AWAY"]["opponent_score"]) == ("Away", 0, 1)
    assert (t["HOME"]["passes"], t["HOME"]["passes_successful"], t["HOME"]["pass_accuracy"]) == (3, 2, 0.667)
    assert (t["HOME"]["shots"], t["HOME"]["goals"], t["HOME"]["tackles"]) == (1, 1, 1)
    assert t["AWAY"]["pass_accuracy"] is None                            # 0 passes: no division by zero


def test_zone_grid_and_edges(gold):
    z = {r["zone_id"]: r for r in rows(gold, "select * from gold_zone_occupancy where player_id = 'H01'")}
    assert z[0]["seconds"] == 1
    assert z[23]["seconds"] == 2                     # x = 104.9 and the clipped x = 105 / y = 68 stay in the last cell
    assert z[14]["seconds"] == 7 and z[14]["share_of_tracked_seconds"] == 0.7
    assert (z[23]["x_min"], z[23]["x_max"], z[23]["y_min"], z[23]["y_max"]) == (87.5, 105.0, 51.0, 68.0)


def test_pass_network(gold):
    n = {(r["passer_id"], r["receiver_id"]): r for r in rows(gold, "select * from gold_pass_network")}
    assert set(n) == {("H01", "H02"), ("H02", "H01")}
    assert (n[("H01", "H02")]["passes"], n[("H01", "H02")]["passes_successful"]) == (2, 1)
    assert n[("H01", "H02")]["passer_name"] == "H. One"


def test_shots_goal_distance_and_running_score(gold):
    s = rows(gold, "select * from gold_shots order by ts")
    assert [r["type"] for r in s] == ["shot", "goal", "shot"]
    assert [(r["score_home_after"], r["score_away_after"]) for r in s] == [(0, 0), (1, 0), (1, 0)]
    assert (s[1]["attacking_goal_x"], s[1]["distance_to_goal_m"], s[1]["is_goal"]) == (105, 5.0, True)
    assert (s[2]["attacking_goal_x"], s[2]["distance_to_goal_m"]) == (0, 10.0)   # AWAY attacks x = 0


def test_player_5min_window(gold):
    w = rows(gold, "select * from gold_player_5min where player_id = 'H01'")
    assert len(w) == 1 and (w[0]["window_start_ts"], w[0]["window_end_ts"]) == (0, 300)
    assert w[0]["tracked_seconds"] == 10 and w[0]["coverage"] == 0.033
    assert (w[0]["passes"], w[0]["goals"]) == (2, 1)


def test_reconciliation_tests_catch_a_wrong_score(tmp_path):
    silver = tmp_path / "silver"
    _write_silver(silver, home_score=2)              # events hold 1 home goal, matches says 2
    run = _dbt(tmp_path, silver, "build")
    assert run.returncode != 0
    assert "assert_goals_equal_score" in run.stdout and "FAIL" in run.stdout
