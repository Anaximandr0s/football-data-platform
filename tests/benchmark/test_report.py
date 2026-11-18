"""benchmark_report: the numbers of docs/performance.md, on fixed measurements."""
import json

import benchmark_report as br


def test_percentiles_are_nearest_rank():
    p = br.percentiles(list(range(1, 101)))
    assert (p["n"], p["p50"], p["p95"], p["p99"], p["max"]) == (100, 50, 95, 99, 100)
    assert br.percentiles([]) == {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
    assert br.percentiles([7.0])["p99"] == 7.0


def test_drain_is_the_first_time_after_the_stop_with_nothing_left():
    samples = [[0, 50], [10, 40], [12, 5], [14, 0], [16, 0]]
    assert br.drain_seconds(samples, stop=10) == 4
    assert br.drain_seconds([[10, 9], [20, 3]], stop=10) is None          # never drained in the samples


def test_a_lag_that_oscillates_is_not_growing_one_that_climbs_is():
    saw = [[t, (t % 10) * 500] for t in range(0, 91)]                      # batches: up and down
    climb = [[t, t * 100] for t in range(0, 91)]
    assert not br.growing(saw, 0, 90)
    assert br.growing(climb, 0, 90)


def test_back_to_normal_waits_for_the_lag_to_stay_under_the_baseline():
    samples = [[t, 900 if 100 < t < 130 else 100] for t in range(90, 170)]
    assert br.back_to_normal(samples, restart=100, baseline=200) == 30
    assert br.back_to_normal([[101, 900], [105, 100]], restart=100, baseline=200) is None   # not held 10 s


def reader(growing=False, drain=5.0, peak=100):
    return {"growing": growing, "drain_s": drain, "peak_lag": peak}


def level(n, **spark):
    return {"level": n, "readers": {"bronze-writer": reader(), "spark": reader(**spark), "live-page": reader()},
            "achieved_msgs_per_s": 1000.0 * n, "target_msgs_per_s": 1000.0 * n, "live_delay_ms": br.percentiles([100]),
            "host_cpu": br.percentiles([0.5]), "mem_available_min_mib": 4000, "cpu_cores": {"spark-worker": 1.5,
                                                                                         "kafka": 0.4}}


def test_the_limit_is_the_first_level_a_reader_cannot_keep_up_with():
    assert br.limit_level([level(1), level(2), level(3, drain=45.0), level(4, growing=True)]) == 3
    assert br.limit_level([level(1), level(2, drain=None)]) == 2
    assert br.limit_level([level(1), level(2)]) is None


def results():
    speed = {"match": "m002", "seconds": 300, "target_msgs_per_s": 270.0,
             "kafka_msgs_per_s": br.percentiles([260, 270, 280]), "bronze_rows_per_s": br.percentiles([250, 270]),
             "spark_rows_per_s": br.percentiles([200, 210]), "live_delay_ms": br.percentiles([300, 500, 1500]),
             "app_p95_ms": 700.0, "window_s": br.percentiles([8.0, 12.0])}
    return {"generated_at": "2026-11-17 12:00 UTC", "commit": "abc1234", "file": "x.json",
            "machine": {"cpu": "test CPU", "threads": 12, "ram_gib": 14.5},
            "speeds": [{**speed, "speed": 1}, {**speed, "speed": 10}, {**speed, "speed": 60}],
            "freshness": {"match": "m001", "run_id": "5af42a3a-0000", "gold_ready_s": 290.0,
                          "steps": [{"step": "bronze", "start_s": 0, "seconds": 9, "cpu_s": 3.0, "peak_mib": 600},
                                    {"step": "silver", "start_s": 10, "seconds": 190, "cpu_s": 400.0, "peak_mib": 2100},
                                    {"step": "gold", "start_s": 210, "seconds": 60, "cpu_s": 90.0, "peak_mib": 900}]},
            "spark": {"batch_s": br.percentiles([8.9, 9.2, 9.5])},
            "load": [level(1), level(2, drain=50.0)], "safety": {"stopped": False, "reason": None},
            "stack_peak_mib": 6100.0,
            "reliability": {"runs": 20, "success_slo": 0.94, "success_raw": 0.85, "on_purpose": 3, "retries": 1,
                            "runs_with_retries": 1},
            "recovery": [{"service": "bronze-writer", "baseline": 5000, "peak": 30000, "back_to_normal_s": 25.0}],
            "final_check": {"rebuilt": ["m001", "m002"], "freshness_green": True, "goldstale_firing": False}}


def test_the_slo_verdicts_use_x1_for_latency_and_the_normal_runs_for_success():
    v = {x["slo"]: x["pass"] for x in br.slo_verdicts(results())}
    assert v == {"Live delay p95 < 2 s": True, "Freshness < 10 min": True, "Run success >= 95 %": False}


def test_bottlenecks_name_spark_batches_and_the_first_reader_over_the_limit():
    found = " ".join(br.bottlenecks(results()))
    assert "Spark Structured Streaming batches** take 9.2 s" in found
    assert "at 2 matches at x60, spark (drain 50 s)" in found
    assert "`silver` (190 s" in found


def test_the_report_and_its_charts_are_built_from_the_results_alone(tmp_path):
    r = json.loads(json.dumps(results()))
    names = br.charts(r, tmp_path)
    assert [n.split("/")[-1] for n in names] == ["throughput.png", "latency.png", "load_test.png",
                                                 "freshness_steps.png"]
    assert all((tmp_path / n.split("/")[-1]).stat().st_size > 10_000 for n in names)
    md = br.render(r, names)
    assert "commit `abc1234`" in md and "| Run success >= 95 % | 94.0% over 7 days (all runs: 85.0%) | FAIL |" in md
    assert "**Limit on this laptop: 2 matches at x60.**" in md


def test_an_app_twice_slower_than_the_probe_running_its_code_is_a_bottleneck():
    r = results()
    assert not any("app's own consumer" in b for b in br.bottlenecks(r))          # 700 ms against 1500 ms: fine
    r["speeds"][0] = {**r["speeds"][0], "app_p95_ms": 2665.0, "live_delay_ms": br.percentiles([300, 502])}
    assert any("p95 2,665 ms against 502 ms" in b for b in br.bottlenecks(r))


def test_silver_reading_many_bronze_copies_is_a_bottleneck():
    r = results()
    r["freshness"]["silver_input"] = {"bronze_copies": 27, "bronze_tracking_rows": 2002066,
                                      "kept_tracking_rows": 97416, "written_at": "x"}
    assert any("27 copies, 2,002,066 tracking rows read to keep 97,416" in b for b in br.bottlenecks(r))


def test_the_slowest_reader_is_named_even_within_the_limit():
    found = " ".join(br.bottlenecks(results()))
    assert "**Slowest reader**: spark, 50.0 s to drain at 2 matches" in found


def test_before_and_after_rows_and_chart(tmp_path):
    before, after = results(), results()
    after["freshness"] = {**after["freshness"], "gold_ready_s": 120.0}
    after["spark"] = {"batch_s": br.percentiles([4.0, 4.5, 5.0])}
    after["reliability"] = {**after["reliability"], "since_fix": {"commit": "0d3c37a", "at": 1.0, "runs": 24,
                                                                  "success": 0.958}}
    rows = {r["item"]: (r["before"], r["after"]) for r in br.comparison(before, after)}
    assert rows["Final whistle → Gold ready"] == (290 / 60, 2.0)
    assert rows["Spark batch p50"] == (9.2, 4.5)
    assert rows["Run success since the last fix"][1] == 95.8 and rows["Run success since the last fix"][0] is None
    names = br.charts(json.loads(json.dumps(after)), tmp_path, before)
    assert names[-1].endswith("before_after.png") and (tmp_path / "before_after.png").stat().st_size > 10_000
    md = br.render(after, names, {**before, "file": "b.json"})
    assert "## Before and after fix/performance" in md and "| Spark batch p50 | 9.2 s | 4.5 s |" in md
    assert "since the last fix (`0d3c37a`, 24 runs)" in md
