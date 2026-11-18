"""core: what may start, where it starts, how far it is, which light is on, where each button leads."""
import core
import pytest

M = core.Match("m001", "Perth Glory 1-3 Brisbane Roar", p1_start=10, p1_end=2900, p2_start=3800, p2_end=6600,
               first_goal_ts=330)


def test_start_presets_kickoff_goal_and_the_tv_clock():
    assert core.start_second(M, "kickoff") == 10
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
                        "dagster", "monitoring"}
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
