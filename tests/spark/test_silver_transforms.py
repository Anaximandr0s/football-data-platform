"""Silver transformations on a tiny hand-made match: no Docker, no MinIO, no Iceberg.

Match m1: HOME attacks toward x = 105 in period 1 (left_to_right) and toward x = 0 in period 2
(right_to_left), like m001. Needs pyspark and Java (skipped otherwise).
"""
import pytest

pytest.importorskip("pyspark")

from pyspark.sql import functions as F  # noqa: E402

from spark.silver import checks, transforms  # noqa: E402

K = "kafka_partition int, kafka_offset long, kafka_ts long, ingested_at long"
MATCHES_DDL = ("match_id string, home_score int, away_score int, "
               "home_side_p1 string, home_side_p2 string")


def make(spark, rows, ddl):
    return spark.createDataFrame(rows, ddl)


@pytest.fixture()
def matches(spark):
    return transforms.clean_matches(make(spark, [
        ("m1", 1, 0, "left_to_right", "right_to_left", 0, 1, 0, 1)], MATCHES_DDL + ", " + K))


@pytest.fixture()
def players(spark):
    return transforms.clean_players(make(spark, [
        ("m1", "H01", "HOME", 0, 1, 0, 1), ("m1", "A01", "AWAY", 0, 1, 0, 1)],
        "match_id string, player_id string, team_id string, " + K))


def tracking(spark, rows):
    """rows: (player_id, ts, period, x, y, speed_kmh), with period as tinyint like bronze."""
    full = [("m1", p, ts, per, x, y, s, i % 2 == 0, 0, i, 0, i) for i, (p, ts, per, x, y, s) in enumerate(rows)]
    return make(spark, full, "match_id string, player_id string, ts int, period tinyint, "
                             "x double, y double, speed_kmh double, is_detected boolean, " + K)


def by_ts(df, player="H01"):
    return {r["ts"]: r for r in df.filter(f"player_id = '{player}'").collect()}


def test_dedup_keeps_one_row_per_key_the_latest_and_drops_kafka_columns(spark):
    df = make(spark, [("m1", "H01", 1, 1, 10.0, 10.0, 5.0, 0, 1, 0, 100),
                      ("m1", "H01", 1, 1, 10.0, 10.0, 5.0, 0, 2, 0, 200),
                      ("m1", "H01", 2, 1, 11.0, 10.0, 5.0, 0, 3, 0, 150)],
              "match_id string, player_id string, ts int, period tinyint, x double, y double, "
              "speed_kmh double, " + K)
    out = transforms.dedup(df, ["match_id", "player_id", "ts"])
    assert out.count() == 2
    assert not set(out.columns) & {"kafka_partition", "kafka_offset", "kafka_ts", "ingested_at"}


def test_tracking_gets_team_is_sorted_and_unique(spark, players, matches):
    rows = [("H01", 3, 1, 10.0, 10.0, 5.0), ("A01", 1, 1, 20.0, 20.0, 5.0),
            ("H01", 1, 1, 11.0, 10.0, 5.0), ("H01", 1, 1, 11.0, 10.0, 5.0)]  # shuffled + duplicate
    out = transforms.clean_tracking(tracking(spark, rows), players, matches)
    got = [(r["player_id"], r["ts"], r["team_id"]) for r in out.collect()]
    assert got == [("A01", 1, "AWAY"), ("H01", 1, "HOME"), ("H01", 3, "HOME")]
    assert out.columns == ["match_id", "player_id", "team_id", "period", "ts", "x", "y",
                           "speed_kmh", "is_sprint", "was_corrected", "is_after_gap", "is_detected"]


def test_period_2_is_mirrored_for_both_teams_period_1_is_not(spark, players, matches):
    rows = [("H01", 1, 1, 10.0, 20.0, 5.0), ("H01", 2, 2, 10.0, 20.0, 5.0),
            ("A01", 2, 2, 100.0, 60.0, 5.0)]
    out = transforms.clean_tracking(tracking(spark, rows), players, matches)
    h, a = by_ts(out, "H01"), by_ts(out, "A01")
    assert (h[1]["x"], h[1]["y"]) == (10.0, 20.0)
    assert (h[2]["x"], h[2]["y"]) == (95.0, 48.0)      # 105 - 10, 68 - 20
    assert (a[2]["x"], a[2]["y"]) == (5.0, 8.0)        # AWAY mirrored too


def test_no_mirror_when_home_attacks_left_to_right_in_both_periods(spark, players):
    m = transforms.clean_matches(make(spark, [("m1", 0, 0, "left_to_right", "left_to_right", 0, 1, 0, 1)],
                                      MATCHES_DDL + ", " + K))
    out = transforms.clean_tracking(tracking(spark, [("H01", 1, 2, 10.0, 20.0, 5.0)]), players, m)
    assert (out.first()["x"], out.first()["y"]) == (10.0, 20.0)


def test_positions_are_clipped_and_flagged_before_or_after_the_mirror(spark, players, matches):
    rows = [("H01", 1, 1, -1.5, 30.0, 5.0),    # outside left
            ("H01", 2, 1, 106.0, 70.0, 5.0),   # outside right and top
            ("H01", 3, 1, 50.0, 30.0, 5.0),    # inside
            ("H01", 4, 2, -1.0, 30.0, 5.0)]    # outside, then mirrored to 106 and clipped to 105
    out = by_ts(transforms.clean_tracking(tracking(spark, rows), players, matches))
    assert (out[1]["x"], out[1]["was_corrected"]) == (0.0, True)
    assert (out[2]["x"], out[2]["y"], out[2]["was_corrected"]) == (105.0, 68.0, True)
    assert (out[3]["x"], out[3]["was_corrected"]) == (50.0, False)
    assert (out[4]["x"], out[4]["was_corrected"]) == (105.0, True)


def test_null_speed_stays_null_and_only_above_25_is_a_sprint(spark, players, matches):
    rows = [("H01", 1, 1, 10.0, 10.0, None), ("H01", 2, 1, 10.0, 10.0, 25.0),
            ("H01", 3, 1, 10.0, 10.0, 25.01), ("H01", 4, 1, 10.0, 10.0, 31.0)]
    out = by_ts(transforms.clean_tracking(tracking(spark, rows), players, matches))
    assert out[1]["speed_kmh"] is None and out[1]["is_sprint"] is False
    assert [out[t]["is_sprint"] for t in (2, 3, 4)] == [False, True, True]
    assert out[2]["speed_kmh"] == 25.0   # value untouched


def test_is_after_gap_marks_the_first_second_after_missing_seconds_only(spark, players, matches):
    rows = [("H01", 0, 1, 1.0, 1.0, None), ("H01", 1, 1, 1.0, 1.0, 1.0), ("H01", 2, 1, 1.0, 1.0, 1.0),
            ("H01", 5, 1, 1.0, 1.0, None), ("H01", 6, 1, 1.0, 1.0, 1.0),
            ("A01", 9, 1, 1.0, 1.0, None)]   # a single row of another player: not after a gap
    out = transforms.clean_tracking(tracking(spark, rows), players, matches)
    assert [by_ts(out)[t]["is_after_gap"] for t in (0, 1, 2, 5, 6)] == [False, False, False, True, False]
    assert by_ts(out, "A01")[9]["is_after_gap"] is False
    assert out.count() == 6   # nothing invented across the gap


EVENT_CONTEXT = ("create", "low_block", None, None, "running", None, False, None, None)
RUN_CONTEXT = ("create", "low_block", 0.12, True, "hsr", "behind", True, True, False)


def events(spark, rows):
    full = [("m1", eid, ts, per, "H01", None, "HOME", typ, xs, ys, xe, ye, "n/a",
             *(RUN_CONTEXT if typ == "run" else EVENT_CONTEXT), 0, i, 0, i)
            for i, (eid, ts, per, typ, xs, ys, xe, ye) in enumerate(rows)]
    return make(spark, full, "match_id string, event_id string, ts int, period tinyint, player_id string, "
                             "receiver_id string, team_id string, type string, x_start double, "
                             "y_start double, x_end double, y_end double, outcome string, phase string, "
                             "phase_against string, xthreat double, dangerous boolean, speed_band string, "
                             "subtype string, lead_to_shot boolean, targeted boolean, received boolean, " + K)


def test_events_guide_direction_mirrors_period_2_keeps_nulls_and_is_not_clipped(spark, matches):
    rows = [("m1-e00001", 5, 1, "pass", 10.0, 20.0, 30.0, 40.0),
            ("m1-e00002", 9, 2, "shot", 10.0, 20.0, None, None),
            ("m1-e00003", 9, 1, "shot", 90.0, 34.0, 106.5, 34.0),   # behind the goal line: kept
            ("m1-e00003", 9, 1, "shot", 90.0, 34.0, 106.5, 34.0)]   # duplicate
    out = {r["event_id"]: r for r in transforms.clean_events(events(spark, rows), matches, "guide").collect()}
    assert len(out) == 3
    assert (out["m1-e00001"]["x_start"], out["m1-e00001"]["x_end"]) == (10.0, 30.0)
    assert (out["m1-e00002"]["x_start"], out["m1-e00002"]["y_start"]) == (95.0, 48.0)
    assert out["m1-e00002"]["x_end"] is None and out["m1-e00002"]["y_end"] is None
    assert out["m1-e00003"]["x_end"] == 106.5


def test_events_per_team_direction_mirrors_away_events_only_in_every_period(spark, matches):
    rows = [("m1-e00001", 1, 1, "shot", 90.0, 30.0, 100.0, 34.0)]   # HOME, period 1
    home = events(spark, rows)
    away = events(spark, [("m1-e00002", 2, 2, "shot", 90.0, 30.0, 100.0, 34.0)]) \
        .withColumn("team_id", F.lit("AWAY"))
    h = transforms.clean_events(home, matches, "per_team").first()
    a = transforms.clean_events(away, matches, "per_team").first()
    assert (h["x_start"], h["y_start"], h["x_end"]) == (90.0, 30.0, 100.0)   # HOME untouched
    assert (a["x_start"], a["y_start"], a["x_end"], a["y_end"]) == (15.0, 38.0, 5.0, 34.0)
    default = transforms.clean_events(away, matches).first()          # per_team is the default
    assert (default["x_start"], default["y_start"]) == (15.0, 38.0)
    with pytest.raises(ValueError):
        transforms.clean_events(home, matches, "nonsense")


def test_runs_follow_the_per_team_frame_and_keep_their_context(spark, matches):
    away_run = events(spark, [("m1-r00001", 3, 2, "run", 90.0, 30.0, 100.0, 34.0)]) \
        .withColumn("team_id", F.lit("AWAY"))
    r = transforms.clean_events(away_run, matches).first()
    assert (r["type"], r["x_start"], r["x_end"]) == ("run", 15.0, 5.0)     # mirrored like an AWAY action
    assert (r["subtype"], r["xthreat"], r["targeted"], r["received"]) == ("behind", 0.12, True, False)


def test_ball_is_mirrored_in_period_2_and_not_clipped(spark, matches):
    df = make(spark, [("m1", 1, 1, 10.0, 20.0, 0.5, "HOME", 0, 1, 0, 1),
                      ("m1", 2, 2, 10.0, 20.0, 0.5, "AWAY", 0, 2, 0, 2),
                      ("m1", 3, 2, -2.0, 20.0, None, None, 0, 3, 0, 3)],
              "match_id string, ts int, period tinyint, x double, y double, z double, possession string, " + K)
    out = {r["ts"]: r for r in transforms.clean_ball(df, matches).collect()}
    assert (out[1]["x"], out[2]["x"], out[2]["y"]) == (10.0, 95.0, 48.0)
    assert [out[t]["possession"] for t in (1, 2, 3)] == ["HOME", "AWAY", None]   # not mirrored: it is a team
    assert out[3]["x"] == 107.0 and out[3]["z"] is None   # 105 - (-2), left outside on purpose


def test_measure_counts_goals_and_corrections(spark, players, matches):
    t = transforms.clean_tracking(
        tracking(spark, [("H01", 1, 1, -1.0, 10.0, None), ("H01", 2, 1, 10.0, 10.0, 26.0)]), players, matches)
    e = transforms.clean_events(events(spark, [("m1-e00001", 1, 1, "goal", 100.0, 34.0, 105.0, 34.0)]), matches)
    b = transforms.clean_ball(make(spark, [("m1", 1, 1, 1.0, 1.0, 0.0, "HOME", 0, 1, 0, 1)],
                                   "match_id string, ts int, period tinyint, x double, y double, z double, "
                                   "possession string, " + K),
                              matches)
    m = checks.measure({"tracking": 2}, t, e, b, players, matches)
    assert m["tracking"]["was_corrected"] == 1 and m["tracking"]["speed_null"] == 1
    assert m["tracking"]["detected"] == 1 and m["ball_with_possession"] == 1
    assert m["events_by_type"] == {"goal": 1}
    assert m["tracking"]["sprints"] == 1 and m["tracking"]["outside_after_clip"] == 0
    assert m["goals_home_away"] == [1, 0] and m["score_home_away"] == [1, 0]
    assert all(ok for _, ok, _ in checks.evaluate(m, None))


# ---- pure Python: the comparison with the ingestion manifest (no Spark involved) ----

def _metrics(**over):
    base = {"keys_unique": {"tracking": True, "events": True, "ball": True, "players": True},
            "rows": {"tracking": 10, "events": 4, "ball": 5, "players": 3, "matches": 1},
            "tracking": {"was_corrected": 2, "speed_null": 3, "team_null": 0, "outside_after_clip": 0,
                         "detected": 6},
            "shot_avg_x": {"HOME": [88.0, 10], "AWAY": [15.0, 8]},
            "goals_home_away": [1, 0], "score_home_away": [1, 0],
            "events_by_type": {"pass": 2, "goal": 1, "run": 1}, "ball_with_possession": 4}
    base.update(over)
    return base


MANIFEST = {"tracking_rows": 10, "events": 4, "ball_rows": 5, "players": 3,
            "rows_outside_pitch": 2, "rows_speed_null": 3, "rows_detected": 6, "ball_rows_with_possession": 4,
            "events_by_type": {"pass": 2, "goal": 1, "run": 1}}


def test_evaluate_passes_when_everything_matches_the_manifest():
    assert all(ok for _, ok, _ in checks.evaluate(_metrics(), MANIFEST))


def test_evaluate_fails_on_a_wrong_row_count_or_goal_count_or_duplicates():
    bad_rows = checks.evaluate(_metrics(rows={"tracking": 11, "events": 4, "ball": 5, "players": 3, "matches": 1}),
                               MANIFEST)
    assert [n for n, ok, _ in bad_rows if not ok] == ["tracking: rows after dedup = ingestion manifest"]
    bad_goals = checks.evaluate(_metrics(goals_home_away=[2, 0]), None)
    assert [n for n, ok, _ in bad_goals if not ok] == ["events: goals equal the final score"]
    dup = _metrics(keys_unique={"tracking": False, "events": True, "ball": True, "players": True})
    assert [n for n, ok, _ in checks.evaluate(dup, None) if not ok] == ["tracking: one row per key"]


def test_evaluate_blocks_a_run_counted_as_an_action_even_when_the_total_matches():
    swapped = _metrics(events_by_type={"pass": 3, "goal": 1})     # same 4 rows, the run became a pass
    assert [n for n, ok, _ in checks.evaluate(swapped, MANIFEST) if not ok] == ["events: rows per type = manifest"]


def test_evaluate_blocks_lost_possession_or_detection_flags():
    lost = _metrics(ball_with_possession=0, tracking={**_metrics()["tracking"], "detected": 0})
    assert sorted(n for n, ok, _ in checks.evaluate(lost, MANIFEST) if not ok) == [
        "ball: seconds with possession = manifest", "tracking: detected rows = manifest rows_detected"]


def test_evaluate_blocks_events_in_the_wrong_frame_but_not_a_handful_of_shots():
    """HOME shots averaging x = 51 (the signature of the old literal rule) must stop the write."""
    wrong = checks.evaluate(_metrics(shot_avg_x={"HOME": [51.8, 26], "AWAY": [30.0, 20]}), None)
    assert [n for n, ok, _ in wrong if not ok] == ["events: HOME shots are on the half it attacks (frame of Silver)"]
    assert [n for n, ok, _ in wrong if "AWAY" in n and ok]            # AWAY at 30 is fine
    few = checks.evaluate(_metrics(shot_avg_x={"HOME": [10.0, 2], "AWAY": [90.0, 1]}), None)
    assert all(ok for _, ok, _ in few)                                 # 1 or 2 shots: not judged
    none = checks.evaluate(_metrics(shot_avg_x={}), None)
    assert all(ok for _, ok, _ in none)                                # a match without shots: nothing to judge
