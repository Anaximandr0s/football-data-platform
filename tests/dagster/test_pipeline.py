"""The rules of the Dagster pipeline: when a replay is over, what a Soda result means, and the shape of the asset graph
(order, blocking checks, the DuckDB pool, retries)."""
import pytest

pytest.importorskip("dagster")

from football_platform.replays import finished, match_of, replay_ends  # noqa: E402
from football_platform.soda import failed_checks, passed  # noqa: E402

M1, M1_LATER, M2 = "m001-20261116T101503Z", "m001-20261116T120000Z", "m002-20261116T101600Z"


def test_a_replay_is_over_when_its_tracking_reaches_the_last_second_of_its_match():
    ends = replay_ends([(M1, {"match_id": "m001", "p2_end_ts": 6025}), (M2, {"match_id": "m002", "p2_end_ts": 6128}),
                        (None, {"match_id": "m003", "p2_end_ts": 6000})])          # no header: ignored
    assert ends == {M1: ("m001", 6025), M2: ("m002", 6128)}
    tracking = [(M1, 6024), (M2, 6128), (None, 7000), (M1_LATER, 7000)]      # M1_LATER: no matches message seen
    assert finished(ends, tracking) == {M2}
    assert finished(ends, tracking + [(M1, 6025)]) == {M1, M2}
    assert match_of(M1) == "m001"


def summary(checks, errors=0):
    return {"passed": sum(c[2] == "pass" for c in checks), "failed": sum(c[2] == "fail" for c in checks),
            "errors": errors, "checks": [{"name": n, "table": t, "outcome": o} for n, t, o in checks]}


def test_a_soda_result_fails_its_table_and_never_hides_an_error():
    s = summary([("goals = score", "gold_shots", "fail"), ("no duplicates", "gold_events", "pass"),
                 ("thin window", "gold_pressing", "warn"), ("could not run", "gold_events", "unknown")])
    assert not passed(s, "gold_shots") and passed(s, "gold_pressing")
    assert failed_checks(s, "gold_events") == ["could not run"]
    assert not passed(summary([("ok", "gold_shots", "pass")], errors=1), "gold_shots")
    assert passed(summary([("ok", "silver_tracking", "pass")]))


def test_the_chain_runs_in_order_and_soda_blocks_what_follows(defs):
    graph = defs.resolve_asset_graph()
    key = defs.resolve_assets_def("silver").key
    assert [k.to_user_string() for k in graph.get(key).parent_keys] == ["bronze"]
    staging = [k for k in graph.get_all_asset_keys() if k.to_user_string().startswith("stg_")]
    assert len(staging) == 5 and all(key in graph.get(k).parent_keys for k in staging)
    from football_platform.assets import soda_gold, soda_silver

    specs = [*soda_silver.check_specs, *soda_gold.check_specs]
    assert all(s.blocking for s in specs)
    assert [s.asset_key for s in soda_silver.check_specs] == [key]
    gold_checked = {s.asset_key.to_user_string() for s in soda_gold.check_specs}
    report = graph.get(defs.resolve_assets_def("match_report").key)
    assert {k.to_user_string() for k in report.parent_keys} == gold_checked and len(gold_checked) == 16


def test_the_duckdb_steps_share_one_pool_and_spark_and_dbt_retry(defs):
    job = defs.resolve_job_def("match_pipeline")
    pools = {n.name: n.definition.pool for n in job.nodes}
    assert pools["gold"] == pools["soda_gold"] == pools["match_report"] == "duckdb"
    assert pools["silver"] is None and pools["bronze"] is None
    retries = {n.name: n.definition.retry_policy for n in job.nodes}
    assert retries["silver"].max_retries == retries["gold"].max_retries == 2
    assert job.partitions_def.name == "match_id"


def test_a_sensor_and_a_schedule_drive_the_chain(defs):
    sensor = defs.resolve_sensor_def("replay_end")
    assert sensor.job_name == "match_pipeline"
    assert defs.resolve_schedule_def("nightly_quality_schedule").cron_schedule == "0 3 * * *"


@pytest.mark.parametrize("inject_damage", [False, True])
def test_the_soda_checks_read_their_config_and_report_per_table(defs, monkeypatch, inject_damage):
    import dagster as dg

    from football_platform import assets

    asked = []

    def fake_soda(context, layer, damage):
        asked.append((layer, damage))
        return summary([("goals = score", "gold_shots", "fail" if damage else "pass"),
                        ("one row per key", "silver_tracking", "fail" if damage else "pass")])

    monkeypatch.setattr(assets, "soda_run", fake_soda)
    config = {"config": {"inject_damage": inject_damage}}
    instance = dg.DagsterInstance.ephemeral()
    result = defs.resolve_job_def("nightly_quality").execute_in_process(
        run_config={"ops": {"silver_soda_silver": config, "soda_gold": config}}, instance=instance,
        raise_on_error=False)
    verdict = {e.asset_key.path[-1]: e.passed for e in result.get_asset_check_evaluations()}
    assert sorted(asked) == [("gold", inject_damage), ("silver", inject_damage)]
    assert verdict["silver"] is not inject_damage and verdict["gold_shots"] is not inject_damage
    assert verdict["gold_events"] is True and len(verdict) == 17
    from football_platform.sensors import run_entry

    entry = run_entry(instance, result.dagster_run)
    assert entry["status"] == ("FAILURE" if inject_damage else "SUCCESS") and entry["trigger"] == "manual"
    assert {s["step"] for s in entry["steps"]} == {"silver_soda_silver", "soda_gold"}
    assert sum(not c["passed"] for c in entry["checks"]) == (2 if inject_damage else 0) and len(entry["checks"]) == 17
