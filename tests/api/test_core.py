"""core: what may start, where it starts, how far it is, which light is on, where each button leads."""
import core
import pytest

M = core.Match("m001", "Perth Glory 1-3 Brisbane Roar", p1_start=10, p1_end=2900, p2_start=3800, p2_end=6600,
               first_goal_ts=330)


def test_start_presets_kickoff_goal_and_the_tv_clock():
    assert core.start_second(M, "kickoff") == 0                         # from the first second: a whole match
    assert core.start_second(M, "goal") == 300                          # 30 s before the ball was in the goal
    assert core.start_second(M, "12:30") == 10 + 750
    assert core.start_second(M, "45:00") == 3800                        # second kick-off
    assert core.start_second(M, "47:30") == 3800 + 150
    assert core.start_second(core.Match("m", "x", 0, 1, 2, 3, first_goal_ts=10), "goal") == 0   # never before kick-off


@pytest.mark.parametrize("start", ["", "90:01", "4:5", "12:60", "abc", "120:00"])
def test_a_bad_start_is_refused_in_plain_words(start):
    with pytest.raises(core.Refused):
        core.start_second(M, start)


def test_no_goal_no_goal_preset():
    with pytest.raises(core.Refused, match="no goal"):
        core.start_second(core.Match("m", "x", 0, 1, 2, 3, first_goal_ts=None), "goal")


def test_the_whitelist_of_a_start():
    assert core.check_start(M, 10, True, {}) == 10
    for match, speed, prepared, running, why in (
            (None, 1, True, {}, "unknown match"), (M, 1, False, {}, "no prepared files"),
            (M, 0, True, {}, "speed"), (M, 61, True, {}, "speed"), (M, 1.5, True, {}, "speed"), (M, True, True, {}, "speed"),
            (M, "5", True, {}, "speed"),
            (M, 1, True, {"m001": "m001-20261118T100000Z"}, "already playing"),
            (M, 1, True, {"m002": "a", "m003": "b"}, "2 replays are already playing")):
        with pytest.raises(core.Refused, match=why):
            core.check_start(match, speed, prepared, running)


def test_progress_comes_from_the_last_second_sent():
    assert core.progress(M, None) == {"last_ts": None, "clock": "–", "share": 0.0}
    p = core.progress(M, 10 + 31 * 60 + 44)
    assert p["clock"] == "31:44" and 0 < p["share"] < 0.5
    assert core.progress(M, 3800 + 125)["clock"] == "47:05"
    assert core.progress(M, 9999)["share"] == 1.0


def test_status_lights():
    lights = core.box_status({"prepared_matches": 4, "replays_running": 1, "kafka_up": 1, "spark_report_age_s": 12,
                              "app_up": 1, "live_up": 1, "minio_up": 1, "bronze_writer_up": 1,
                              "soda_failed": {"silver": 0, "gold": 0}, "freshness_max_s": 150, "dagster_up": 1,
                              "runs_failed_latest": 0, "prometheus_up": 1})
    assert set(lights.values()) == {"green"}
    lights = core.box_status({"kafka_up": 0, "spark_report_age_s": 300, "soda_failed": {"silver": 2},
                              "dagster_up": 1, "runs_failed_latest": 1})
    assert (lights["kafka"], lights["spark"], lights["silver"], lights["gold"], lights["dagster"],
            lights["producer"]) == ("red", "red", "red", "grey", "red", "grey")


def test_warnings_name_the_missing_job_and_the_command():
    w = " ".join(core.warnings({"streaming_up": 0, "bronze_writer_up": 0, "kafka_up": 1}))
    assert "make streaming" in w and "make up" in w
    assert core.warnings({"streaming_up": 1, "bronze_writer_up": 1, "kafka_up": 1}) == []
    assert "Open the Live page once" in " ".join(core.warnings({"streaming_up": 1, "bronze_writer_up": 1, "app_up": 1,
                                                                "live_up": 0}))


BASE = {"app": "http://localhost:8501", "grafana": "http://localhost:3001", "kafka_ui": "http://localhost:8081",
        "spark_master": "http://localhost:8082", "spark_driver": "http://localhost:4040",
        "minio": "http://localhost:9001", "dagster": "http://localhost:3000", "prometheus": "http://localhost:9090",
        "alertmanager": "http://localhost:9093"}


def test_every_box_has_buttons_and_page_links_carry_the_match_and_view():
    out = core.links(BASE, "m002")
    assert set(out) == {"skillcorner", "producer", "kafka", "spark", "live", "bronze", "silver", "gold", "analysis",
                        "dagster", "monitoring", "control"}
    urls = {b["label"]: b["url"] for buttons in out.values() for b in buttons}
    assert urls["Live page"] == "http://localhost:8501/live_match?match=m002"
    assert urls["Match story (fan)"] == "http://localhost:8501/match_story?view=fan&match=m002"
    assert urls["MinIO: bronze bucket"] == "http://localhost:9001/browser/bronze"
    assert {u for u in urls.values() if "/d/" in u} >= {f"http://localhost:3001/d/{d}" for d in
                                                        ("slo", "infrastructure", "streaming", "pipeline")}
    assert core.links(BASE)["live"][0]["url"] == "http://localhost:8501/live_match"


def test_containers_list_the_running_ones_and_the_missing_ones():
    rows = core.containers(cpu={"football-platform-kafka-1": 0.5}, memory={"football-platform-kafka-1": 400 * 2**20},
                           limit={"football-platform-kafka-1": 1024 * 2**20}, started={"football-platform-kafka-1": 100.0},
                           now=160.0)
    assert rows[0] == {"name": "kafka", "running": True, "cpu_cores": 0.5, "memory_mib": 400.0, "limit_mib": 1024.0,
                       "uptime_s": 60.0}
    missing = {r["name"] for r in rows if not r["running"]}
    assert "bronze-writer" in missing and "kafka" not in missing


def test_every_box_has_a_role_and_numbers_are_formatted_plainly():
    assert set(core.ROLES) == set(core.NUMBERS) == set(core.links(BASE))
    assert all(len(text) < 260 for _, text in core.ROLES.values())
    assert [core.fmt(v, k) for v, k in ((1234.4, "rate"), (0.52, "s"), (0.958, "pct"), (None, "s"),
                                        (float("nan"), "pct"), (1, "yesno"))] == ["1,234/s", "0.5 s", "96%", "–", "–",
                                                                                  "yes"]


def test_the_steps_of_a_run_become_chips_in_order():
    running = core.chips({"bronze": "SUCCESS", "silver": "IN_PROGRESS"}, "STARTED")
    assert [(c["label"], c["state"]) for c in running] == [("Bronze", "done"), ("Silver", "running"),
                                                           ("Soda", "waiting"), ("Gold", "waiting"),
                                                           ("Soda", "waiting"), ("report", "waiting")]
    failed = core.chips({"bronze": "SUCCESS", "silver": "SUCCESS", "silver_soda_silver": "FAILURE"}, "FAILURE")
    assert [c["state"] for c in failed] == ["done", "done", "failed", "not built", "not built", "not built"]


def bench_results():
    pct = {"n": 1, "p50": 1078.0, "p95": 1.0, "p99": 1.0, "max": 1.0}
    reader = {"growing": False, "drain_s": 10.0, "peak_lag": 1}
    return {"generated_at": "2026-11-17 23:41 UTC",
            "speeds": [{"speed": 1, "live_delay_ms": {"p95": 491.9}}, {"speed": 60, "kafka_msgs_per_s": pct}],
            "freshness": {"gold_ready_s": 150.0}, "spark": {"batch_s": {"p50": 3.8}},
            "load": [{"level": 4, "readers": {"spark": reader}}],
            "recovery": [{"service": "bronze-writer", "back_to_normal_s": 47.4}],
            "reliability": {"runs": 41, "on_purpose": 10, "success_slo": 0.909, "since_fix": {"commit": "0d3c37a",
                                                                                              "runs": 26, "success": 0.962}}}


def test_the_panel_says_one_number_per_idea_each_with_its_source():
    verdicts = [{"slo": "Live delay p95 < 2 s", "measured": "0.49 s (x1)", "pass": True},
                {"slo": "Run success >= 95 %", "measured": "90.9% over 7 days", "pass": False}]
    panel = core.performance(bench_results(), verdicts, (215, 215), (15, 15), "18 Nov 2026 11:12 UTC")
    assert [h["title"] for h in panel["hero"]] == ["Live delay", "Ready after the final whistle", "Quality checks",
                                                   "Goal minutes exact", "Capacity"]
    assert [h["value"] for h in panel["hero"]] == ["0.5 s", "2.5 min", "215 / 215", "15 / 15", "4 matches at x60"]
    assert all(h["source"] and h["icon"] for h in panel["hero"])
    assert panel["journey"] == ["A player moves", "0.5 s", "Live page", "2.5 min after the final whistle",
                                "Full statistics, checked and stored"]
    fail = next(d for d in panel["details"] if d["title"].startswith("Run success"))
    assert fail["value"] == "FAIL" and "below the 95 % goal (3 failed)" in fail["line"] and "96.2% of 26 runs" in fail["line"]


def test_without_a_benchmark_the_panel_keeps_the_quality_numbers():
    panel = core.performance(None, [], (210, 215), (14, 15), None)
    assert [h["title"] for h in panel["hero"]] == ["Quality checks", "Goal minutes exact"]
    assert panel["journey"] == [] and panel["details"] == []
