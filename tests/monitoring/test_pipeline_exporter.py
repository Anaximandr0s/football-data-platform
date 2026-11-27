"""The pipeline exporter: Dagster runs, freshness, dbt, Soda and Spark progress turned into metrics."""

import pytest

pytest.importorskip("prometheus_client")
import pipeline_exporter as pe  # noqa: E402


def gql_run(run_id, job, status, start, end, partition=None, run_key=None, steps=(), purpose=None):
    tags = [{"key": "dagster/partition", "value": partition}] if partition else []
    if purpose:
        tags.append({"key": "purpose", "value": purpose})
    if run_key:
        tags += [{"key": "dagster/run_key", "value": run_key}, {"key": "dagster/sensor_name", "value": "replay_end"}]
    return {
        "runId": run_id,
        "jobName": job,
        "status": status,
        "startTime": start,
        "endTime": end,
        "tags": tags,
        "stepStats": [{"stepKey": k, "status": s, "startTime": a, "endTime": b} for k, s, a, b in steps],
    }


def values(samples, name):
    return {tuple(s.labels.values()): s.value for s in samples if s.name == name}


RUNS = pe.runs_from_graphql(
    [
        gql_run(
            "r1",
            "match_pipeline",
            "SUCCESS",
            1000,
            1300,
            "m001",
            "m001-20261116T100000Z",
            [("bronze", "SUCCESS", 1001, 1010), ("gold", "SUCCESS", 1100, 1240)],
        ),
        gql_run(
            "r2",
            "match_pipeline",
            "FAILURE",
            2000,
            2050,
            "m001",
            None,
            [("bronze", "SUCCESS", 2001, 2010), ("silver_soda_silver", "FAILURE", 2020, 2050)],
            purpose="demo",
        ),
        gql_run(
            "r3",
            "match_pipeline",
            "SUCCESS",
            3000,
            3100,
            "m002",
            "m002-20261116T110000Z",
            [("bronze", "SUCCESS", 3001, 3020)],
        ),
    ]
)


def test_graphql_runs_take_the_shape_dagster_writes_to_runs_json():
    r1 = RUNS[0]
    assert (r1["match_id"], r1["replay_id"], r1["started"]) == ("m001", "m001-20261116T100000Z", 1001)
    assert RUNS[1]["replay_id"] is None  # a manual run is not a replay
    assert r1["steps"][1] == {"step": "gold", "status": "SUCCESS", "start": 1100, "end": 1240}


def test_runs_are_counted_and_the_latest_run_of_each_match_says_if_it_failed():
    s = pe.dagster_samples(RUNS, now=4000)
    assert values(s, "football_dagster_runs") == {
        ("match_pipeline", "FAILURE", "true"): 1,  # the demo
        ("match_pipeline", "SUCCESS", "false"): 2,
    }
    assert values(s, "football_dagster_latest_run_failed") == {
        ("match_pipeline", "m001", "r2"): 1.0,
        ("match_pipeline", "m002", "r3"): 0.0,
    }
    assert values(s, "football_dagster_step_duration_seconds")[("match_pipeline", "bronze")] == 19  # the latest
    assert values(s, "football_dagster_last_success_timestamp_seconds") == {("m001",): 1300, ("m002",): 3100}


def test_freshness_follows_the_data_quality_page_rule():
    s = pe.freshness_samples(RUNS, now=4000)
    assert values(s, "football_gold_freshness_seconds") == {("m001", "m001-20261116T100000Z"): 239}  # 1240 - 1001
    waiting = values(s, "football_gold_waiting_seconds")
    assert waiting[("m001", "m001-20261116T100000Z")] == 0
    assert waiting[("m002", "m002-20261116T110000Z")] == 4000 - 3001  # no gold step after its whistle


def test_dbt_counts_tests_and_names_the_failed_ones():
    results = {
        "results": [
            {"unique_id": "test.football.not_null_gold_shots_match_id.5f3a", "status": "fail"},
            {"unique_id": "test.football.unique_gold_events_event_id.77aa", "status": "pass"},
            {"unique_id": "model.football.gold_shots", "status": "success"},
        ]
    }
    s = pe.dbt_samples(results, written_at=123.0)
    assert values(s, "football_dbt_tests") == {("fail",): 1, ("pass",): 1}
    assert values(s, "football_dbt_test_failed") == {("not_null_gold_shots_match_id",): 1.0}
    assert pe.dbt_samples(None, None) == []


def test_soda_results_are_grouped_by_dimension_and_failed_checks_named():
    results = {
        "silver": {
            "checks": [
                {"name": "row_count > 0", "table": "tracking", "outcome": "pass"},
                {"name": "duplicate_count(id) = 0", "table": "tracking", "outcome": "fail"},
            ]
        }
    }
    mapping = {
        "tracking": {
            "row_count > 0": {"dimension": "completeness", "plain": "tracking is not empty"},
            "duplicate_count(id) = 0": {"dimension": "uniqueness", "plain": "no duplicate row"},
        }
    }
    s = pe.soda_samples(results, mapping, {"silver": 99.0})
    assert values(s, "football_soda_checks") == {
        ("silver", "completeness", "pass"): 1,
        ("silver", "uniqueness", "fail"): 1,
    }
    assert values(s, "football_soda_check_failed") == {("silver", "uniqueness", "tracking", "no duplicate row"): 1}


def test_the_newest_soda_file_of_a_layer_wins(tmp_path):
    import os

    for name, mtime in (("silver.json", 100), ("silver-damaged.json", 200), ("gold.json", 50)):
        (tmp_path / name).write_text("{}")
        os.utime(tmp_path / name, (mtime, mtime))
    files = pe.newest_soda_files(tmp_path)
    assert (files["silver"].name, files["gold"].name) == ("silver-damaged.json", "gold.json")


def test_spark_progress_becomes_per_query_metrics():
    progress = {
        "players-5min": {
            "reported_at": 50.0,
            "running": True,
            "offsets_behind_latest": 12.0,
            "input_rows_per_second": 30.0,
            "processed_rows_per_second": 40.0,
            "batch_duration_ms": 1500,
        }
    }
    s = pe.spark_samples(progress)
    assert values(s, "football_spark_batch_duration_seconds") == {("players-5min",): 1.5}
    assert values(s, "football_spark_offsets_behind_latest") == {("players-5min",): 12.0}
    assert pe.spark_samples(None) == []


def test_a_run_still_queued_has_no_start_and_does_not_break_freshness():
    queued = pe.runs_from_graphql(
        [gql_run("r4", "match_pipeline", "QUEUED", None, None, "m001", "m001-20261117T105800Z")]
    )
    s = pe.freshness_samples(RUNS + queued, now=4000)
    assert values(s, "football_gold_freshness_seconds") == {("m001", "m001-20261116T100000Z"): 239}  # unchanged


def test_one_failing_source_does_not_hide_the_others(monkeypatch):
    def broken(now):
        raise ValueError("unreadable file")

    monkeypatch.setattr(
        pe,
        "SOURCES",
        {"dagster": broken, "spark": lambda now: [pe.Sample("football_spark_query_running", {"query": "q"}, 1.0)]},
    )
    s = pe.collect_samples(now=1.0)
    assert values(s, "football_exporter_source_up") == {("dagster",): 0.0, ("spark",): 1.0}
    assert values(s, "football_spark_query_running") == {("q",): 1.0}
