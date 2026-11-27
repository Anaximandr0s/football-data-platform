"""The Control Center's edges against small stand-ins: an HTTP server for Prometheus and Dagster, a DuckDB file, a
fake Kafka consumer and a real child process for the producer."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import confluent_kafka
import core
import duckdb
import pytest
import services

PROM = {"data": {"result": [{"metric": {"job": "kafka"}, "value": [0, "1"]},
                            {"metric": {"job": "minio"}, "value": [0, "0"]}]}}
RUNS = {"data": {"runsOrError": {"results": [
    {"runId": "r1", "status": "STARTED", "endTime": None,
     "tags": [{"key": "dagster/partition", "value": "m001"}, {"key": "replay_id", "value": "m001-X"}],
     "stepStats": [{"stepKey": "bronze", "status": "SUCCESS"}, {"stepKey": "silver", "status": "IN_PROGRESS"}]}]}}}


@pytest.fixture
def server():
    """Answers GET with Prometheus' payload and POST (GraphQL) with Dagster's, recording each request body."""
    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload):
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - the name http.server calls
            self._send(PROM)

        def do_POST(self):  # noqa: N802
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send(RUNS)

        def log_message(self, *_):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{httpd.server_port}", bodies=bodies)
    httpd.shutdown()
    httpd.server_close()


def test_prometheus_values_by_label_and_grey_lights_when_it_is_down(server):
    prom = services.Prometheus(server.url)
    assert prom.by("up", "job") == {"kafka": 1.0, "minio": 0.0}
    assert prom.value("up") == 1.0
    down = services.Prometheus("http://127.0.0.1:9")
    assert down.query("up") == [] and down.value("up") is None


def test_dagster_runs_in_flight_and_the_run_of_one_replay(server, monkeypatch):
    monkeypatch.setattr(services, "DAGSTER", server.url)
    assert services.running_pipeline_runs() == [{"run_id": "r1", "status": "STARTED", "match_id": "m001",
                                                  "replay_id": "m001-X", "step": "silver"}]
    run = services.replay_run("m001-X")
    assert server.bodies[-1]["variables"] == {"rid": "m001-X"}
    assert (run["run_id"], run["status"]) == ("r1", "STARTED")
    assert [c["state"] for c in run["chips"]][:2] == ["done", "running"]
    monkeypatch.setattr(services, "DAGSTER", "http://127.0.0.1:9")
    assert services.running_pipeline_runs() == [] and services.replay_run("m001-X") is None


def test_the_match_library_comes_from_gold_with_the_first_goal(tmp_path, monkeypatch):
    gold = tmp_path / "gold.duckdb"
    with duckdb.connect(str(gold)) as con:
        con.execute("create table gold_match_library (match_id varchar, home_team_short varchar, away_team_short "
                    "varchar, home_score int, away_score int, match_date date, p1_start_ts int, p1_end_ts int, "
                    "p2_start_ts int, p2_end_ts int)")
        con.execute("insert into gold_match_library values ('m001', 'BRI', 'ADE', 2, 3, '2025-03-15', 0, 2890, 2899, "
                    "6025), ('m002', 'BRI', 'PER', 0, 0, '2025-01-04', 0, 2800, 2810, 5900)")
        con.execute("create table gold_events as select 'm001' match_id, 'goal' type, 724 goal_ts")
    monkeypatch.setattr(services, "GOLD", gold)
    library = services.gold_matches()
    assert list(library) == ["m001", "m002"]                                   # newest first
    assert library["m001"] == core.Match("m001", "BRI 2-3 ADE · 15 Mar 2025", 0, 2890, 2899, 6025, 724)
    assert library["m002"].first_goal_ts is None


class Stop(Exception):
    pass


def test_the_kafka_watch_keeps_each_replays_last_second_and_its_rate(monkeypatch):
    def msg(topic, replay, ts):
        return SimpleNamespace(error=lambda: None, topic=lambda: topic, value=lambda: json.dumps({"ts": ts}).encode(),
                               headers=lambda: [("replay_id", replay.encode())] if replay else [])

    batches = [[msg("foot-tracking", "m001-A", 9), msg("foot-ball", "m001-A", 12), msg("foot-events", "m001-A", 99),
                msg("foot-tracking", None, 50)]]

    class Consumer:
        def __init__(self, _conf):
            pass

        def list_topics(self, timeout):
            return SimpleNamespace(topics={t: SimpleNamespace(partitions={0: None}) for t in services.REPLAY_TOPICS})

        def get_watermark_offsets(self, _tp, timeout):
            return 0, 7

        def assign(self, partitions):
            assert {tp.offset for tp in partitions} == {7}                     # from the end of each topic

        def consume(self, _n, _timeout):
            if not batches:
                raise Stop
            return batches.pop()

    monkeypatch.setattr(confluent_kafka, "Consumer", Consumer)
    watch = services.KafkaWatch()
    with pytest.raises(Stop):
        watch.run()
    assert watch.last("m001-A") == 12 and watch.last("m002-B") is None
    assert watch.rate("m001-A") == pytest.approx(3 / 5)


def test_a_producer_that_stops_before_sending_is_refused(monkeypatch, tmp_path):
    match = core.Match("m001", "label", 0, 2890, 2899, 6025, None)
    monkeypatch.setattr(services, "ROOT", tmp_path)                            # no ingestion package there: exit 1
    started = []
    real_popen = services.subprocess.Popen
    monkeypatch.setattr(services.subprocess, "Popen", lambda *a, **k: started.append(real_popen(*a, **k)) or started[-1])
    with pytest.raises(core.Refused, match="stopped before sending"):
        services.Replays().start(match, 60, "kickoff", prepared=True)
    assert started[0].stdout.closed


def test_a_replay_that_ends_by_itself_is_finished_not_stopped(monkeypatch):
    class Done:
        def __init__(self, *_a, **_k):
            import io
            self.stdout = io.StringIO("replay_id=m001-A\n")

        def poll(self):
            return 0

    monkeypatch.setattr(services.subprocess, "Popen", Done)
    replays = services.Replays()
    replays.start(core.Match("m001", "label", 0, 2890, 2899, 6025, None), 60, "kickoff", prepared=True)
    assert replays.running() == {} and not replays.stop("m001") and not replays.stop("m404")
    snap = replays.snapshot()["m001"]
    assert (snap["finished"], snap["stopped"], snap["running"]) == (True, False, False)
    assert snap["started_at"] <= dt.datetime.now().timestamp()
