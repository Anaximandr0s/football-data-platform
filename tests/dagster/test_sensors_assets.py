"""The final-whistle sensor on a fake Kafka, the run log, and each pipeline step with its command replaced."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

dg = pytest.importorskip("dagster")
pytest.importorskip("dagster_dbt")

M1 = "m001-20261127T100000Z"


class Msg:
    def __init__(self, topic, offset, replay, value):
        self._topic, self._offset, self._replay, self._value = topic, offset, replay, json.dumps(value).encode()

    def topic(self):
        return self._topic

    def partition(self):
        return 0

    def offset(self):
        return self._offset

    def headers(self):
        return [("replay_id", self._replay.encode())]

    def value(self):
        return self._value

    def error(self):
        return None


class FakeKafka:
    """confluent_kafka.Consumer over one partition per topic."""

    def __init__(self, topics: dict[str, list[dict]]):
        self.log = {t: [Msg(t, i, M1, v) for i, v in enumerate(rows)] for t, rows in topics.items()}
        self.position: dict[str, int] = {}

    def list_topics(self, timeout):
        return SimpleNamespace(topics={t: SimpleNamespace(partitions={0: None}) for t in self.log})

    def get_watermark_offsets(self, tp, timeout):
        return 0, len(self.log[tp.topic])

    def assign(self, partitions):
        self.position = {tp.topic: tp.offset for tp in partitions}

    def consume(self, n, timeout):
        out = []
        for topic, start in self.position.items():
            out += self.log[topic][start : start + n]
            self.position[topic] = start + len(out)
        return out

    def close(self):
        pass


@pytest.fixture
def sensors(defs, tmp_path, monkeypatch):
    from football_platform import sensors

    monkeypatch.setattr(sensors, "PIPELINE_OUT", tmp_path)
    return sensors


def test_the_final_whistle_starts_one_run_for_its_match_and_adds_the_partition(sensors, monkeypatch):
    kafka = FakeKafka(
        {"foot-matches": [{"match_id": "m001", "p2_end_ts": 9}], "foot-tracking": [{"ts": ts} for ts in range(10)]}
    )
    monkeypatch.setattr(sensors, "Consumer", lambda _conf: kafka)
    instance = dg.DagsterInstance.ephemeral()

    first = sensors.replay_end(dg.build_sensor_context(instance=instance))
    assert first.run_requests == []  # first tick: an old replay is no final whistle
    assert first.dynamic_partitions_requests[0].partition_keys == ["m001"]

    second = sensors.replay_end(dg.build_sensor_context(instance=instance, cursor=json.dumps({"0": 0})))
    (request,) = second.run_requests
    assert (request.run_key, request.partition_key, request.tags) == (M1, "m001", {"replay_id": M1})


def test_every_finished_run_is_logged_once_with_the_asset_graph(defs, sensors, monkeypatch):
    from football_platform import assets

    monkeypatch.setattr(assets, "soda_run", lambda *_: {"passed": 1, "failed": 0, "errors": 0, "checks": []})
    instance = dg.DagsterInstance.ephemeral()
    result = defs.resolve_job_def("nightly_quality").execute_in_process(instance=instance, raise_on_error=False)
    context = SimpleNamespace(instance=instance, dagster_run=result.dagster_run)
    sensors.log_run(context)
    sensors.log_run(context)
    runs = json.loads((sensors.PIPELINE_OUT / "runs.json").read_text(encoding="utf-8"))
    graph = json.loads((sensors.PIPELINE_OUT / "graph.json").read_text(encoding="utf-8"))
    assert [r["run_id"] for r in runs] == [result.run_id]
    nodes = {n["key"]: n for n in graph["assets"]}
    assert nodes["silver"]["deps"] == ["bronze"] and nodes["silver"]["checks"] == ["soda_silver"]


def step_context(replay: str | None = M1):
    return SimpleNamespace(
        partition_key="m001",
        run=SimpleNamespace(tags={"replay_id": replay} if replay else {}, run_id="r1"),
        log=dg.get_dagster_logger(),
    )


def test_a_command_that_fails_fails_the_step_with_its_report(defs):
    from football_platform import assets

    assert assets.run(step_context(), [sys.executable, "-c", "print('ok')"]) == "ok\n"
    with pytest.raises(dg.Failure, match="exited with 3"):
        assets.run(step_context(), [sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"])


@pytest.mark.parametrize(("code", "done"), [(0, True), (1, False)])
def test_check_bronze_reads_the_runs_replay_and_tells_missing_from_crashed(defs, monkeypatch, code, done):
    from football_platform import assets

    asked = []

    def fake_run(args, **_):
        asked.append(args)
        return subprocess.CompletedProcess(args, code, "report", "")

    monkeypatch.setattr(assets.subprocess, "run", fake_run)
    assert assets.check_bronze(step_context()) == (done, "report")
    assert asked[0][-4:] == ["--match", "m001", "--replay", M1]
    monkeypatch.setattr(assets.subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, 2, "", "boom"))
    with pytest.raises(dg.Failure, match="exited with 2"):
        assets.check_bronze(step_context(None))


def test_the_bronze_step_fails_when_rows_are_still_missing_at_the_deadline(defs, monkeypatch):
    from football_platform import assets

    monkeypatch.setattr(assets, "BRONZE_WAIT_S", 0)
    step = assets.bronze.op.compute_fn.decorated_fn
    monkeypatch.setattr(assets, "check_bronze", lambda _c: (False, "tracking MISSING"))
    with pytest.raises(dg.Failure, match="still missing in Bronze"):
        step(step_context())
    monkeypatch.setattr(assets, "check_bronze", lambda _c: (True, "tracking OK"))
    assert "tracking OK" in step(step_context()).metadata["check_bronze"].value


def test_silver_submits_the_job_for_the_runs_match_and_replay(defs, monkeypatch):
    from football_platform import assets

    asked = []
    monkeypatch.setattr(assets, "run", lambda _c, args, **_: asked.append(args) or "wrote lake.silver.tracking")
    result = assets.silver.op.compute_fn.decorated_fn(step_context())
    assert asked[0][0] == "spark-submit" and asked[0][-4:] == ["--match", "m001", "--replay", M1]
    assert result.metadata["silver report"].value == "wrote lake.silver.tracking"


@pytest.mark.parametrize("damage", [False, True])
def test_soda_run_reads_the_result_file_of_its_layer(defs, monkeypatch, tmp_path, damage):
    from football_platform import assets

    monkeypatch.setattr(assets, "SODA_OUT", tmp_path)
    asked = []
    monkeypatch.setattr(assets, "run", lambda _c, args, ok_codes: asked.append((args, ok_codes)))
    (tmp_path / ("gold-damaged.json" if damage else "gold.json")).write_text('{"passed": 3}', encoding="utf-8")
    assert assets.soda_run(step_context(), "gold", damage) == {"passed": 3}
    assert asked[0][1] == (0, 1) and ("--inject-damage" in asked[0][0]) is damage


def test_the_match_report_tells_the_match_as_gold_has_it(defs, monkeypatch, tmp_path):
    import duckdb

    from football_platform import assets

    gold = tmp_path / "gold.duckdb"
    with duckdb.connect(str(gold)) as con:
        con.execute(
            "create table gold_match_library as select 'm001' match_id, 'BRI' home_team_short, "
            "'ADE' away_team_short, 2 home_score, 3 away_score, 0.76 tracked_share"
        )
        con.execute(
            "create table gold_team_match_stats as select 'm001' match_id, 'HOME' team_id, 'BRI' team_short, "
            "2 score, 104.2 distance_km, 410 passes, 12 shots, 2 goals"
        )
    monkeypatch.setattr(assets, "GOLD_DB", gold)
    monkeypatch.setattr(assets, "REPORTS", tmp_path / "reports")
    step = assets.match_report.op.compute_fn.decorated_fn
    assert step(step_context()).metadata["score"] == "2-3"
    report = json.loads((tmp_path / "reports" / "m001.json").read_text(encoding="utf-8"))
    assert (report["home"], report["replay_id"], report["teams"][0]["passes"]) == ("BRI", M1, 410)
    context = step_context()
    context.partition_key = "m404"
    with pytest.raises(dg.Failure, match="not in Gold"):
        step(context)
