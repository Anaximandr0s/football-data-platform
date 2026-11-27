"""The Control Center's routes: two actions only, both whitelisted; the read-only payloads the page uses."""

import io
import os

import pytest

pytest.importorskip("fastapi")
os.environ["CONTROL_CENTER_WATCH"] = "0"  # no Kafka in tests
import core  # noqa: E402
import main  # noqa: E402
import services  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

LIB = {m: core.Match(m, f"Team A 1-0 Team B · {m}", 10, 2900, 3800, 6600, 330) for m in ("m001", "m002", "m003")}


class FakeProc:
    """A producer that printed its replay id and runs until terminated."""

    count = 0

    def __init__(self, args, **_kw):
        FakeProc.count += 1
        match = args[args.index("--match") + 1]
        self.args, self.code = args, None
        self.stdout = io.StringIO(f"replay_id={match}-2026111{FakeProc.count}T120000Z\n")

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15

    def wait(self):
        return self.code


class FakeProm:
    def value(self, _expr):
        return 1.0

    def by(self, _expr, _label):
        return {}

    def query(self, _expr):
        return []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(services, "gold_matches", lambda: LIB)
    monkeypatch.setattr(services, "running_pipeline_runs", lambda: [])
    monkeypatch.setattr(services.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(main, "prepared", lambda m: m in LIB)
    monkeypatch.setattr(main, "prom", FakeProm())
    monkeypatch.setattr(main, "replays", services.Replays())
    with TestClient(main.app) as c:
        yield c


def test_start_and_stop_a_replay(client):
    r = client.post("/api/replay/start", json={"match": "m001", "speed": 5, "start": "goal"})
    assert r.status_code == 200 and r.json()["replay_id"].startswith("m001-")
    proc = main.replays.items["m001"]["proc"]
    assert proc.args[proc.args.index("--start") + 1] == "300"  # 30 s before the ball was in the goal
    assert proc.args[proc.args.index("--speed") + 1] == "5"
    assert client.post("/api/replay/stop", json={"match": "m001"}).json() == {"match": "m001", "stopped": True}
    assert client.post("/api/replay/stop", json={"match": "m001"}).status_code == 404  # not playing any more


@pytest.mark.parametrize(
    "body, why",
    [
        ({"match": "m009", "speed": 1}, "unknown match"),
        ({"match": "m001", "speed": 0}, "speed"),
        ({"match": "m001", "speed": 61}, "speed"),
        ({"match": "m001", "speed": 2.5}, "speed"),
        ({"match": "m001", "speed": "10; rm -rf /"}, "speed"),
        ({"match": "m001", "speed": 1, "start": "95:00"}, "90:00"),
    ],
)
def test_the_whitelist_refuses_in_plain_words(client, body, why):
    r = client.post("/api/replay/start", json=body)
    assert r.status_code == 409 and why in r.json()["detail"]
    assert main.replays.items == {}  # nothing started


def test_one_replay_per_match_and_two_at_most(client):
    assert client.post("/api/replay/start", json={"match": "m001", "speed": 1}).status_code == 200
    again = client.post("/api/replay/start", json={"match": "m001", "speed": 1})
    assert again.status_code == 409 and "already playing" in again.json()["detail"]
    assert client.post("/api/replay/start", json={"match": "m002", "speed": 1}).status_code == 200
    third = client.post("/api/replay/start", json={"match": "m003", "speed": 1})
    assert third.status_code == 409 and "2 replays are already playing" in third.json()["detail"]


@pytest.mark.parametrize(
    "method, path",
    [
        ("get", "/api/replay/start"),
        ("delete", "/api/replay/stop"),
        ("post", "/api/containers"),
        ("post", "/api/run"),
        ("put", "/api/box/kafka"),
        ("post", "/api/docker/restart"),
    ],
)
def test_nothing_else_can_be_done(client, method, path):
    assert getattr(client, method)(path).status_code in (404, 405)


def test_payloads_of_the_page(client):
    status = client.get("/api/status").json()
    assert set(status) >= {"lights", "warnings", "replays", "pipeline_runs", "live_moving", "stored_moving"}
    assert set(status["lights"]) == set(core.ROLES)
    box = client.get("/api/box/live").json()
    assert box["title"] == "Live page" and box["links"][0]["url"].endswith("/live_match")
    assert client.get("/api/box/nothing").status_code == 404
    assert [m["match_id"] for m in client.get("/api/matches").json()] == ["m001", "m002", "m003"]
    assert isinstance(client.get("/api/containers").json(), list)
    assert client.get("/").status_code == 200 and client.get("/logo.svg").status_code == 200


def test_a_playing_replay_shows_its_progress_from_what_kafka_received(client, monkeypatch):
    client.post("/api/replay/start", json={"match": "m001", "speed": 1})
    replay = main.replays.items["m001"]["replay_id"]
    monkeypatch.setattr(main.watch, "last_ts", {replay: 10 + 600})
    play = client.get("/api/status").json()["replays"][0]
    assert play["progress"]["clock"] == "10:00" and play["running"] and play["live_url"].endswith("?match=m001")


def test_a_stopped_card_leaves_after_30_s_and_clear_removes_it_at_once(client, monkeypatch):
    client.post("/api/replay/start", json={"match": "m001", "speed": 1})
    client.post("/api/replay/start", json={"match": "m002", "speed": 1})
    client.post("/api/replay/stop", json={"match": "m001"})
    now = 1_000_000.0
    monkeypatch.setattr(main.time, "time", lambda: now)
    assert {p["match_id"] for p in client.get("/api/status").json()["replays"]} == {"m001", "m002"}
    now += core.CARD_STAYS_S
    assert [p["match_id"] for p in client.get("/api/status").json()["replays"]] == ["m002"]

    client.post("/api/replay/stop", json={"match": "m002"})
    assert client.post("/api/replay/clear").json() == {"cleared": 2}
    assert client.get("/api/status").json()["replays"] == []
