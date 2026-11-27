"""services.py: the Control Center's edges: Prometheus, Dagster, the Gold file, Kafka (what each replay has really
sent) and the producer processes. Everything else is in core.py."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

import core
import duckdb

ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
DAGSTER = os.getenv("DAGSTER_GRAPHQL", "http://dagster-webserver:3000/graphql")
GOLD = Path(os.getenv("GOLD_DUCKDB_PATH", ROOT / "data" / "football.duckdb"))
REPLAY_TOPICS = ("foot-tracking", "foot-ball", "foot-events")


def http_json(url: str, body: dict | None = None, timeout: float = 5) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class Prometheus:
    def __init__(self, url: str = PROMETHEUS):
        self.url = url

    def query(self, expr: str) -> list[dict]:
        q = urllib.parse.urlencode({"query": expr})
        try:
            return http_json(f"{self.url}/api/v1/query?{q}")["data"]["result"]
        except OSError:                      # Prometheus stopped: the page shows grey lights, not an error
            return []

    def value(self, expr: str) -> float | None:
        result = self.query(expr)
        return float(result[0]["value"][1]) if result else None

    def by(self, expr: str, label: str) -> dict[str, float]:
        return {r["metric"].get(label, ""): float(r["value"][1]) for r in self.query(expr)}


def running_pipeline_runs() -> list[dict]:
    """Dagster match_pipeline runs queued or running: the stored path of the diagram moves while there is one."""
    q = ('{ runsOrError(filter: {statuses: [QUEUED, STARTING, STARTED], pipelineName: "match_pipeline"}) '
         '{ ... on Runs { results { runId status tags { key value } stepStats { stepKey status } } } } }')
    try:
        runs = http_json(DAGSTER, {"query": q})["data"]["runsOrError"]["results"]
    except (OSError, KeyError):
        return []
    out = []
    for r in runs:
        tags = {t["key"]: t["value"] for t in r["tags"]}
        step = next((s["stepKey"] for s in r["stepStats"] if s["status"] == "IN_PROGRESS"), None)
        out.append({"run_id": r["runId"], "status": r["status"], "match_id": tags.get("dagster/partition"),
                    "replay_id": tags.get("replay_id"), "step": step})
    return out


def replay_run(replay_id: str) -> dict | None:
    """The Dagster run the sensor started for a replay (its run key is the replay id), None before it exists."""
    q = ('query ($rid: String!) { runsOrError(filter: {tags: [{key: "dagster/run_key", value: $rid}]}, limit: 1) '
         '{ ... on Runs { results { runId status endTime stepStats { stepKey status } } } } }')
    try:
        runs = http_json(DAGSTER, {"query": q, "variables": {"rid": replay_id}})["data"]["runsOrError"]["results"]
    except (OSError, KeyError):
        return None
    if not runs:
        return None
    r = runs[0]
    return {"run_id": r["runId"], "status": r["status"], "ended_at": r["endTime"],
            "chips": core.chips({s["stepKey"]: s["status"] for s in r["stepStats"]}, r["status"])}


def gold_matches() -> dict[str, core.Match]:
    """The match library of Gold, with the second of each match's first goal (the ball in the goal)."""
    con = duckdb.connect(str(GOLD), read_only=True)
    try:
        rows = con.execute("""
            select l.match_id, l.home_team_short, l.away_team_short, l.home_score, l.away_score, l.match_date,
                   l.p1_start_ts, l.p1_end_ts, l.p2_start_ts, l.p2_end_ts, g.first_goal_ts
            from gold_match_library l
            left join (select match_id, min(goal_ts) as first_goal_ts from gold_events where type = 'goal'
                       group by match_id) g using (match_id)
            order by l.match_date desc""").fetchall()
    finally:
        con.close()
    return {r[0]: core.Match(r[0], f"{r[1]} {r[3]}-{r[4]} {r[2]} · {r[5]:%d %b %Y}", int(r[6]), int(r[7]), int(r[8]),
                             int(r[9]), None if r[10] is None else int(r[10])) for r in rows}


class KafkaWatch(threading.Thread):
    """Reads the replay topics from their end: per replay, the last match second really sent (tracking and ball) and
    the messages of the last seconds (messages per second)."""

    def __init__(self, bootstrap: str = BOOTSTRAP):
        super().__init__(daemon=True, name="kafka-watch")
        self.bootstrap = bootstrap
        self.last_ts: dict[str, int] = {}
        self.recent: dict[str, deque] = {}
        self.lock = threading.Lock()

    def run(self) -> None:
        from confluent_kafka import Consumer, TopicPartition

        c = Consumer({"bootstrap.servers": self.bootstrap, "group.id": f"control-center-{time.time_ns()}",
                      "enable.auto.commit": False, "log_level": 3})
        meta = c.list_topics(timeout=10).topics
        c.assign([TopicPartition(t, p, c.get_watermark_offsets(TopicPartition(t, p), timeout=10)[1])
                  for t in REPLAY_TOPICS if t in meta for p in meta[t].partitions])
        while True:
            msgs = c.consume(1000, 0.5)
            now = time.time()
            with self.lock:
                for msg in msgs:
                    if msg.error():
                        continue
                    replay = dict(msg.headers() or []).get("replay_id")
                    if not replay:
                        continue
                    replay = replay.decode()
                    self.recent.setdefault(replay, deque()).append(now)
                    if msg.topic() != "foot-events":
                        ts = json.loads(msg.value()).get("ts")
                        if ts is not None and ts > self.last_ts.get(replay, -1):
                            self.last_ts[replay] = ts

    def rate(self, replay: str, window_s: float = 5.0) -> float:
        with self.lock:
            q = self.recent.get(replay, deque())
            while q and q[0] < time.time() - window_s:
                q.popleft()
            return len(q) / window_s

    def last(self, replay: str) -> int | None:
        with self.lock:
            return self.last_ts.get(replay)


class Replays:
    """The producers this Control Center started: at most core.MAX_RUNNING at once, one per match."""

    def __init__(self, bootstrap: str = BOOTSTRAP):
        self.bootstrap = bootstrap
        self.items: dict[str, dict] = {}       # match_id -> its latest replay, running or not
        self.lock = threading.Lock()

    def running(self) -> dict[str, str]:
        with self.lock:
            return {m: r["replay_id"] for m, r in self.items.items() if r["proc"].poll() is None}

    def start(self, m: core.Match | None, speed, start: str, prepared: bool) -> str:
        """Checks the whitelist (core.check_start) and starts the producer, under one lock: two clicks at the same time
        cannot both pass the limit."""
        with self.lock:
            running = {mid: r["replay_id"] for mid, r in self.items.items() if r["proc"].poll() is None}
            speed = core.check_start(m, speed, prepared, running)
            start_ts = core.start_second(m, start)
            proc = subprocess.Popen([sys.executable, "-m", "ingestion.producer_foot", "--match", m.match_id,
                                     "--speed", str(speed), "--start", str(start_ts), "--bootstrap", self.bootstrap],
                                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env={**os.environ, "PYTHONPATH": str(ROOT)})
            replay = next((line.strip().removeprefix("replay_id=") for line in proc.stdout
                           if line.startswith("replay_id=")), None)
            if replay is None:
                proc.stdout.close()
                raise core.Refused(f"the producer of {m.match_id} stopped before sending (exit {proc.wait()})")
            threading.Thread(target=proc.stdout.read, daemon=True).start()   # a full pipe would block it
            self.items[m.match_id] = {"proc": proc, "replay_id": replay, "speed": speed, "start_ts": start_ts,
                                      "started_at": time.time(), "stopped": False}
            return replay

    def stop(self, match_id: str) -> bool:
        with self.lock:
            item = self.items.get(match_id)
            if item is None or item["proc"].poll() is not None:
                return False
            item["stopped"] = True
            item["proc"].terminate()
            return True

    def snapshot(self) -> dict[str, dict]:
        """Per match: replay id, speed, running, and whether it reached the final whistle (ended by itself)."""
        with self.lock:
            out = {}
            for m, r in self.items.items():
                code = r["proc"].poll()
                out[m] = {"replay_id": r["replay_id"], "speed": r["speed"], "start_ts": r["start_ts"],
                          "started_at": r["started_at"], "running": code is None,
                          "finished": code == 0 and not r["stopped"], "stopped": r["stopped"]}
            return out
