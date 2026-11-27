"""benchmark.py (`make benchmark`): measures the platform like a production team and saves the raw numbers to
data/benchmark/<date>.json; scripts/benchmark_report.py turns them into docs/performance.md.

  speeds       x1 and x10: a 5-minute slice of a match (no final whistle, no pipeline run); x60: a whole match,
               whose normal Dagster run gives final whistle -> Gold per step, with CPU and memory
  load         1, 2, 3, 4 matches at once at x60, the Dagster replay sensor paused (re-enabled in a finally)
  recovery     bronze-writer, then the Spark streaming driver, restarted in the middle of a replay at x10
  rebuild      Gold rebuilt once for the matches of the load test (tag purpose=benchmark), then freshness checked

Three threads run along: a probe that runs the Live page's own code (live.route) on every message and records its
delay; a sampler of the lag of bronze-writer and Spark, every second; a safety guard that stops the producers when the
laptop is in danger (memory, CPU, disk). Needs the stack, `make streaming`, `make dagster`, `make monitoring` and
data/prepared/m001-m004. About 50 minutes; the laptop is busy meanwhile. Run from the repository root."""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import UTC, datetime
from pathlib import Path

import benchmark_report as br
import pyarrow.parquet as pq
from confluent_kafka import Consumer, TopicPartition

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "streamlit"))
import live  # noqa: E402 - the Live page's own code

log = logging.getLogger("benchmark")
BOOTSTRAP = os.getenv("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:29092")
PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
DAGSTER = os.getenv("DAGSTER_GRAPHQL", "http://localhost:3000/graphql")
ALERTMANAGER = os.getenv("ALERTMANAGER_URL", "http://localhost:9093")
OUT = ROOT / "data" / "benchmark"
PROGRESS = ROOT / "data" / "streaming" / "progress.json"
REPLAY_TOPICS = {f"foot-{t}": t for t in ("tracking", "events", "ball", "players", "matches")}
STATS_TOPIC = "foot-live-stats"
LOCATION = {"repositoryLocationName": "football_platform.definitions", "repositoryName": "__repository__"}
CONTAINERS = 'name=~"football-platform-.+|streaming-5min"'
STEP_CONTAINERS = 'name=~"football-platform-(dagster-daemon|spark-worker)-1"'
SAFETY = {"mem_available_mib": 1536, "cpu": 0.95, "cpu_seconds": 30, "disk_free": 0.10}


# ---------------------------------------------------------------- services


def http_json(url: str, body: dict | None = None, timeout: float = 15) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def gql(query: str, variables: dict | None = None) -> dict:
    answer = http_json(DAGSTER, {"query": query, "variables": variables or {}})
    if "errors" in answer:
        raise RuntimeError(f"Dagster: {answer['errors']}")
    return answer["data"]


def prom_range(expr: str, start: float, end: float, step: int = 15) -> list[float]:
    q = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": step})
    result = http_json(f"{PROMETHEUS}/api/v1/query_range?{q}")["data"]["result"]
    return [float(v) for series in result for _, v in series["values"]]


def prom_by(expr: str, start: float, end: float, label: str, step: int = 15) -> dict[str, list[float]]:
    q = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": step})
    result = http_json(f"{PROMETHEUS}/api/v1/query_range?{q}")["data"]["result"]
    return {s["metric"].get(label, ""): [float(v) for _, v in s["values"]] for s in result}


def prom_at(expr: str, at: float) -> float | None:
    q = urllib.parse.urlencode({"query": expr, "time": at})
    result = http_json(f"{PROMETHEUS}/api/v1/query?{q}")["data"]["result"]
    return float(result[0]["value"][1]) if result else None


def sensor(running: bool) -> None:
    selector = {**LOCATION, "sensorName": "replay_end"}
    if running:
        gql("mutation ($s: SensorSelector!) { startSensor(sensorSelector: $s) { __typename } }", {"s": selector})
    else:
        sid = gql(
            "query ($s: SensorSelector!) { sensorOrError(sensorSelector: $s) { ... on Sensor { sensorState "
            "{ id } } } }",
            {"s": selector},
        )["sensorOrError"]["sensorState"]["id"]
        gql("mutation ($id: String!) { stopSensor(id: $id) { __typename } }", {"id": sid})
    log.info("Dagster replay sensor %s", "running" if running else "paused")


def skip_paused_replays() -> None:
    """Moves the replay sensor's cursor (its next offset per foot-tracking partition) to the end of the topic: the
    replays that ended while it was paused are covered by rebuild(), not by one pipeline run each."""
    c = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": f"benchmark-cursor-{time.time_ns()}", "log_level": 3})
    parts = c.list_topics("foot-tracking", timeout=10).topics["foot-tracking"].partitions
    cursor = {str(p): c.get_watermark_offsets(TopicPartition("foot-tracking", p), timeout=10)[1] for p in parts}
    c.close()
    gql(
        "mutation ($s: SensorSelector!, $c: String) { setSensorCursor(sensorSelector: $s, cursor: $c) { __typename } }",
        {"s": {**LOCATION, "sensorName": "replay_end"}, "c": json.dumps(cursor)},
    )
    log.info("replay sensor cursor moved to the end of foot-tracking: %s", cursor)


class scenario:  # noqa: N801 - used as `with scenario("x60"):`
    """Marks a scenario in data/benchmark/current.json: the pipeline exporter turns it into Grafana annotations."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        (OUT / "current.json").write_text(json.dumps({"scenario": self.name}))
        log.info("scenario %s", self.name)
        return self

    def __exit__(self, *exc):
        (OUT / "current.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- the three threads


class Probe(threading.Thread):
    """Reads every replay topic and foot-live-stats from their end, like the Live page: live.route on every message,
    then delay = now - the producer's timestamp. Also keeps, per replay, the first Kafka time of each match second
    (tracking) and of each complete window (foot-live-stats), and its own lag."""

    def __init__(self):
        super().__init__(daemon=True, name="probe")
        self.delays: list[tuple[float, float]] = []  # (received, delay ms)
        self.first_ms: dict[str, dict[int, int]] = {}  # replay -> ts -> kafka ms
        self.complete_ms: dict[tuple, int] = {}  # (replay, size, index, end_ts) -> kafka ms
        self.lag: list[tuple[float, int]] = []  # filled by the Sampler (it has the ends)
        self.next_offset: dict[tuple[str, int], int] = {}
        self.stop_event = threading.Event()
        self.ready = threading.Event()

    def run(self) -> None:
        c = Consumer(
            {
                "bootstrap.servers": BOOTSTRAP,
                "group.id": f"benchmark-probe-{time.time_ns()}",
                "enable.auto.commit": False,
                "log_level": 3,
            }
        )
        parts = [
            TopicPartition(t, p)
            for t in [*REPLAY_TOPICS, STATS_TOPIC]
            for p in c.list_topics(t, timeout=10).topics[t].partitions
        ]
        start = {(tp.topic, tp.partition): c.get_watermark_offsets(tp, timeout=10)[1] for tp in parts}
        c.assign([TopicPartition(t, p, o) for (t, p), o in start.items()])
        self.next_offset = {k: o for k, o in start.items() if k[0] != STATS_TOPIC}
        self.ready.set()
        states = {}
        while not self.stop_event.is_set():
            for msg in c.consume(1000, 0.5):  # as app/streamlit/live_feed.py
                if msg.error():
                    continue
                if msg.topic() != STATS_TOPIC:
                    self.next_offset[(msg.topic(), msg.partition())] = msg.offset() + 1
                kafka_ms, replay = msg.timestamp()[1], dict(msg.headers() or []).get("replay_id")
                rec = json.loads(msg.value())
                if msg.topic() == STATS_TOPIC:
                    if rec.get("complete"):
                        key = (rec["replay_id"], rec["window_size"], rec["window_index"], rec["window_end_ts"])
                        self.complete_ms.setdefault(key, kafka_ms)
                    continue
                replay = replay.decode() if replay else None
                states = live.route(states, replay, REPLAY_TOPICS[msg.topic()], rec, kafka_ms)
                self.delays.append((time.time(), time.time() * 1000 - kafka_ms))
                if msg.topic() == "foot-tracking" and replay:
                    self.first_ms.setdefault(replay, {}).setdefault(rec["ts"], kafka_ms)
        c.close()

    def delays_between(self, start: float, end: float) -> list[float]:
        return [d for t, d in list(self.delays) if start <= t <= end]

    def window_latencies(self, replay: str) -> list[float]:
        """Seconds from the send of the first tracking second past a window's end + grace to its first complete row."""
        sent = self.first_ms.get(replay, {})
        seconds = sorted(sent)
        out = []
        for (rid, _size, _index, end_ts), done_ms in list(self.complete_ms.items()):
            i = bisect_left(seconds, end_ts + 10)  # rows.GRACE_S
            if rid == replay and i < len(seconds):
                out.append((done_ms - sent[seconds[i]]) / 1000)
        return out


class Sampler(threading.Thread):
    """Every second: the bronze-writer group's lag (committed offsets, without joining the group), the Spark streaming
    lag (its progress file, only when reported in the last 30 s), and the host's memory and CPU for the safety guard."""

    def __init__(self, probe: Probe):
        super().__init__(daemon=True, name="sampler")
        self.probe = probe
        self.bronze: list[tuple[float, int]] = []
        self.spark: list[tuple[float, float]] = []
        self.produced: list[tuple[float, int]] = []
        self.host: list[tuple[float, float, float]] = []  # (t, cpu fraction, MiB available)
        self.danger: str | None = None
        self.stop_event = threading.Event()

    def run(self) -> None:
        c = Consumer(
            {"bootstrap.servers": BOOTSTRAP, "group.id": "bronze-writer", "enable.auto.commit": False, "log_level": 3}
        )
        parts = [TopicPartition(t, p) for t in REPLAY_TOPICS for p in c.list_topics(t, timeout=10).topics[t].partitions]
        cpu_prev, high_cpu_since = _cpu_times(), None
        while not self.stop_event.is_set():
            t = time.time()
            ends = {(tp.topic, tp.partition): c.get_watermark_offsets(tp, timeout=5)[1] for tp in parts}
            committed = c.committed(parts, timeout=5)
            self.bronze.append((t, sum(max(0, ends[(tp.topic, tp.partition)] - max(tp.offset, 0)) for tp in committed)))
            self.produced.append((t, sum(ends.values())))
            read = dict(self.probe.next_offset)
            self.probe.lag.append((t, sum(max(0, ends[k] - read[k]) for k in ends if k in read)))
            spark = _spark_behind(t, ends)
            if spark is not None:
                self.spark.append((t, spark))
            cpu_now = _cpu_times()
            cpu = 1 - (cpu_now[1] - cpu_prev[1]) / max(1, cpu_now[0] - cpu_prev[0])
            cpu_prev, mem = cpu_now, _mem_available_mib()
            self.host.append((t, cpu, mem))
            high_cpu_since = (high_cpu_since or t) if cpu > SAFETY["cpu"] else None
            disk = shutil.disk_usage("/")
            if mem < SAFETY["mem_available_mib"]:
                self.danger = f"only {mem:.0f} MiB of memory available"
            elif high_cpu_since and t - high_cpu_since >= SAFETY["cpu_seconds"]:
                self.danger = f"host CPU above {SAFETY['cpu']:.0%} for {SAFETY['cpu_seconds']} s"
            elif disk.free / disk.total < SAFETY["disk_free"]:
                self.danger = f"disk {disk.free / disk.total:.0%} free"
            time.sleep(max(0.0, 1 - (time.time() - t)))
        c.close()

    def between(self, series: list, start: float, end: float) -> list[list[float]]:
        return [[t, v] for t, v in list(series) if start <= t <= end]


def _cpu_times() -> tuple[int, int]:
    """(total, idle) jiffies of the host (/proc/stat)."""
    fields = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
    return sum(fields), fields[3] + fields[4]


def _mem_available_mib() -> float:
    line = next(x for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable"))
    return int(line.split()[1]) / 1024


def _spark_behind(now: float, ends: dict[tuple[str, int], int]) -> float | None:
    """Messages Spark has not processed yet: Kafka's latest offsets minus the end offsets of each query's last batch,
    for the slowest query. None when no query reported in the last 30 s (a restart): unknown, not zero."""
    try:
        queries = json.loads(PROGRESS.read_text())
    except (OSError, json.JSONDecodeError):  # being replaced by the listener: next second
        return None
    behind = [
        sum(
            max(0, ends[(topic, int(p))] - o)
            for topic, parts in q["end_offsets"].items()
            for p, o in parts.items()
            if (topic, int(p)) in ends
        )
        for q in queries.values()
        if q.get("running") and now - q["reported_at"] < 30 and q.get("end_offsets")
    ]
    return max(behind) if behind else None


# ---------------------------------------------------------------- replays


def produce(
    matches: list[str],
    speed: float,
    start: int = 0,
    seconds: float | None = None,
    sampler: Sampler | None = None,
    stop: threading.Event | None = None,
) -> tuple[float, float, dict[str, str]]:
    """Replays the matches at once; stops them after `seconds`, when `stop` is set or when the safety guard fires.
    (start, stop, replay id per match)."""
    procs = {
        m: subprocess.Popen(
            [
                sys.executable,
                "-m",
                "ingestion.producer_foot",
                "--match",
                m,
                "--speed",
                str(speed),
                "--start",
                str(start),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for m in matches
    }
    replays = {m: _replay_id(p) for m, p in procs.items()}
    for p in procs.values():  # keep reading their output, so a full pipe never blocks them
        threading.Thread(target=p.stdout.read, daemon=True).start()
    t0 = time.time()
    while any(p.poll() is None for p in procs.values()):
        if (seconds and time.time() - t0 >= seconds) or (sampler and sampler.danger) or (stop and stop.is_set()):
            for p in procs.values():
                p.terminate()
        time.sleep(0.5)
    failed = [m for m, p in procs.items() if p.returncode not in (0, -15)]
    if failed:
        raise RuntimeError(f"producer failed for {failed}")
    return t0, time.time(), replays


def _replay_id(proc: subprocess.Popen) -> str:
    for line in proc.stdout:
        if line.startswith("replay_id="):
            return line.strip().removeprefix("replay_id=")
    raise RuntimeError("the producer ended without printing its replay_id")


def target_rate(match: str, start: int, seconds: float | None, speed: float) -> float:
    """Messages per second the producer must send: the match's rows per second of play, times the speed."""
    folder = ROOT / "data" / "prepared" / match
    ts = [
        t
        for name in ("tracking", "events", "ball")
        for t in pq.read_table(folder / f"{name}.parquet", columns=["ts"]).column("ts").to_pylist()
    ]
    end = start + seconds * speed if seconds else max(ts) + 1
    first = max(start, min(ts))
    return sum(first <= t < end for t in ts) / (end - first) * speed


# ---------------------------------------------------------------- scenarios


def speeds(probe: Probe, sampler: Sampler) -> tuple[list[dict], dict]:
    out, x60_replay = [], None
    # 6 minutes: a 5-minute window is crossed whole, + its 10 s of grace
    for speed, match, start, seconds in ((1, "m002", 600, 360), (10, "m003", 600, 360), (60, "m001", 0, None)):
        with scenario(f"x{speed}"):
            t0, t1, replays = produce([match], speed, start, seconds, sampler)
            time.sleep(30)  # the last windows complete, readers drain
        lo = t0 + 30  # skip the first half-minute: ramp-up
        out.append(
            {
                "speed": speed,
                "match": match,
                "seconds": t1 - t0,
                "target_msgs_per_s": target_rate(match, start, seconds, speed),
                "kafka_msgs_per_s": br.percentiles(
                    prom_range(
                        'sum(delta(kafka_topic_partition_current_offset{topic=~"foot-(tracking|events|ball|players|matches)"}'
                        "[30s])) / 30",
                        lo,
                        t1,
                    )
                ),
                "bronze_rows_per_s": br.percentiles(
                    prom_range(
                        'sum(delta(kafka_consumergroup_current_offset{consumergroup="bronze-writer"}[30s])) / 30',
                        lo,
                        t1,
                    )
                ),
                "spark_rows_per_s": br.percentiles(
                    prom_range(
                        "metrics_streaming_driver_spark_streaming_players_5min_processingRate_total_Value", lo, t1
                    )
                ),
                "live_delay_ms": br.percentiles(probe.delays_between(t0, t1 + 30)),
                "app_p95_ms": _ms(
                    prom_at(
                        "histogram_quantile(0.95, sum by (le) (increase("
                        f"football_live_delay_seconds_bucket[{int(t1 - t0) + 30}s])))",
                        t1 + 30,
                    )
                ),
                "window_s": br.percentiles(probe.window_latencies(replays[match])),
                "replay_id": replays[match],
                "t0": t0,
                "t1": t1,
            }
        )
        if speed == 60:
            x60_replay = (match, replays[match])
    return out, freshness(*x60_replay)


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else seconds * 1000


RUN_FIELDS = "runId status startTime endTime tags { key value } stepStats { stepKey status startTime endTime }"


def wait_run(run_key: str | None = None, run_id: str | None = None, timeout: float = 1500) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if run_id:
            run = gql(f'{{ runOrError(runId: "{run_id}") {{ ... on Run {{ {RUN_FIELDS} }} }} }}')["runOrError"]
        else:
            runs = gql(
                f'{{ runsOrError(filter: {{tags: [{{key: "dagster/run_key", value: "{run_key}"}}]}}) '
                f"{{ ... on Runs {{ results {{ {RUN_FIELDS} }} }} }} }}"
            )["runsOrError"]["results"]
            run = runs[0] if runs else None
        if run and run["status"] in ("SUCCESS", "FAILURE", "CANCELED"):
            return run
        time.sleep(10)
    raise TimeoutError(f"no finished run for {run_key or run_id} after {timeout:.0f} s")


def freshness(match: str, replay: str) -> dict:
    """The x60 replay's own Dagster run (started by the sensor): each step, its CPU and peak memory."""
    run = wait_run(run_key=replay)
    steps = sorted((s for s in run["stepStats"] if s["startTime"] and s["endTime"]), key=lambda s: s["startTime"])
    whistle = steps[0]["startTime"]  # quality.freshness: the run's start
    time.sleep(30)  # the last scrape after the run is in
    memory = f"sum(container_memory_working_set_bytes{{{STEP_CONTAINERS}}})"
    idle = prom_at(memory, whistle - 20)
    out = []
    for s in steps:
        start, end = s["startTime"], s["endTime"]
        # CPU counters are scraped every 15 s: under 30 s, a step's share cannot be told from its neighbours'
        cpu = (
            [prom_at(f"sum(container_cpu_usage_seconds_total{{{STEP_CONTAINERS}}})", t) for t in (start, end + 15)]
            if end - start >= 30
            else [None, None]
        )
        peak = prom_at(f"max_over_time({memory}[{max(15, int(end - start) + 15)}s:5s])", end + 15)
        out.append(
            {
                "step": s["stepKey"],
                "status": s["status"],
                "start_s": start - whistle,
                "seconds": end - start,
                "cpu_s": cpu[1] - cpu[0] if None not in cpu else None,
                "peak_mib": peak / 2**20 if peak is not None else None,
                "idle_mib": idle / 2**20 if idle is not None else None,
            }
        )
    gold = next((s for s in steps if s["stepKey"] == "gold" and s["status"] == "SUCCESS"), None)
    return {
        "match": match,
        "replay_id": replay,
        "run_id": run["runId"],
        "status": run["status"],
        "steps": out,
        "gold_ready_s": gold["endTime"] - whistle if gold else None,
        "silver_input": silver_input(match),
    }


def silver_input(match: str) -> dict:
    """What Silver read for the match (its own report, data/quality): Bronze keeps every replay, so Silver reads
    every copy and removes the duplicates."""
    report = json.loads((ROOT / "data" / "quality" / f"silver_{match}.json").read_text(encoding="utf-8"))
    return {
        "bronze_copies": report["bronze_rows"]["matches"],
        "bronze_tracking_rows": report["bronze_rows"]["tracking"],
        "kept_tracking_rows": report["silver_rows"]["tracking"],
        "written_at": report["written_at_utc"],
    }


def load(probe: Probe, sampler: Sampler) -> list[dict]:
    out = []
    for level in (1, 2, 3, 4):
        if sampler.danger:
            break
        matches = [f"m00{i}" for i in range(1, level + 1)]
        with scenario(f"load {level} match{'es' if level > 1 else ''}"):
            before = _last(sampler.produced)
            t0, t1, replays = produce(matches, 60, sampler=sampler)
            produced = _last(sampler.produced) - before
            drained_by = t1 + 120
            while time.time() < drained_by and not _all_drained(probe, sampler, t1):
                time.sleep(2)
            t2 = time.time()
        readers = {}
        for name, series in (("bronze-writer", sampler.bronze), ("spark", sampler.spark), ("live-page", probe.lag)):
            s = sampler.between(series, t0, t2)
            readers[name] = {
                "growing": br.growing(s, t0, t1),
                "drain_s": br.drain_seconds(s, t1),
                "peak_lag": max((v for _, v in s), default=None),
            }
        host = [(c, m) for t, c, m in list(sampler.host) if t0 <= t <= t1]
        cores = prom_by(
            f"sum by (name) (rate(container_cpu_usage_seconds_total{{{CONTAINERS}}}[30s]))", t0 + 30, t1, "name"
        )
        out.append(
            {
                "level": level,
                "matches": matches,
                "replays": replays,
                "seconds": t1 - t0,
                "target_msgs_per_s": sum(target_rate(m, 0, None, 60) for m in matches),
                "achieved_msgs_per_s": produced / (t1 - t0),
                "readers": readers,
                "live_delay_ms": br.percentiles(probe.delays_between(t0, t1)),
                "host_cpu": br.percentiles([c for c, _ in host]),
                "mem_available_min_mib": min((m for _, m in host), default=None),
                "cpu_cores": {
                    n.removeprefix("football-platform-").removesuffix("-1"): br.percentiles(v)["p95"]
                    for n, v in cores.items()
                },
                "t0": t0,
                "t1": t1,
                "t2": t2,
            }
        )
        log.info("load %s: %s", level, {k: (v["drain_s"], v["growing"]) for k, v in readers.items()})
        time.sleep(20)  # cool-down between levels
    return out


def _last(series: list) -> float:
    return series[-1][1] if series else 0


def _all_drained(probe: Probe, sampler: Sampler, stop: float) -> bool:
    return all(s and s[-1][0] > stop and s[-1][1] <= 0 for s in (sampler.bronze, sampler.spark, probe.lag))


def recovery(probe: Probe, sampler: Sampler) -> list[dict]:
    """A replay of m004 at x10: bronze-writer restarted after 90 s, the Spark driver 130 s after it is back; the replay
    goes on until 150 s after the last restart. The restart time is Docker's (the container's new start)."""
    restarts = {
        "bronze-writer": ("football-platform-bronze-writer-1", sampler.bronze),
        "spark-streaming": ("streaming-5min", sampler.spark),
    }
    done, took, stop = {}, {}, threading.Event()

    def restarter():
        time.sleep(90)
        for service, (container, _) in restarts.items():
            asked = time.time()
            subprocess.run(["docker", "restart", container], check=True, capture_output=True)
            started = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.StartedAt}}", container],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            done[service] = datetime.fromisoformat(started.replace("Z", "+00:00")[:26] + "+00:00").timestamp()
            took[service] = time.time() - asked
            log.info("restarted %s (docker restart took %.0f s)", container, took[service])
            time.sleep(130 if service == "bronze-writer" else 150)
        stop.set()

    with scenario("recovery: restarts at x10"):
        threading.Thread(target=restarter, daemon=True).start()
        produce(["m004"], 10, 600, sampler=sampler, stop=stop)
        time.sleep(30)
    out = []
    for service, (_, series) in restarts.items():
        at = done[service]
        before = [v for t, v in series if at - 60 <= t < at]
        after = sampler.between(series, at, at + 240)
        baseline = max(before, default=0)
        out.append(
            {
                "service": service,
                "baseline": baseline,
                "peak": max((v for _, v in after), default=None),
                "back_to_normal_s": br.back_to_normal(after, at, baseline),
                "restart_s": took[service],
            }
        )
    return out


def rebuild(replays: dict[str, str]) -> dict:
    """One Dagster run per match of the load test, tagged with its latest replay (freshness counts it) and
    purpose=benchmark (left out of the run-success objective). Then: freshness green, no GoldStale firing."""
    query = (
        "mutation ($p: ExecutionParams!) { launchRun(executionParams: $p) { __typename ... on LaunchRunSuccess "
        "{ run { runId } } ... on PythonError { message } } }"
    )
    runs = {}
    for match, replay in sorted(replays.items()):
        answer = gql(
            query,
            {
                "p": {
                    "selector": {**LOCATION, "jobName": "match_pipeline"},
                    "executionMetadata": {
                        "tags": [
                            {"key": "dagster/partition", "value": match},
                            {"key": "replay_id", "value": replay},
                            {"key": "purpose", "value": "benchmark"},
                        ]
                    },
                }
            },
        )["launchRun"]
        if answer["__typename"] != "LaunchRunSuccess":
            raise RuntimeError(f"rebuild of {match}: {answer}")
        runs[match] = answer["run"]["runId"]
    statuses = {m: wait_run(run_id=r, timeout=2400)["status"] for m, r in runs.items()}
    time.sleep(45)  # two scrapes, then the rule evaluation
    fresh = {m: prom_at(f'football_gold_freshness_seconds{{match_id="{m}"}}', time.time()) for m in runs}
    alerts = http_json(f"{ALERTMANAGER}/api/v2/alerts")
    return {
        "rebuilt": sorted(runs),
        "runs": runs,
        "statuses": statuses,
        "freshness_s": fresh,
        "freshness_green": all(v is not None and v <= br.SLO["freshness_s"] for v in fresh.values()),
        "goldstale_firing": any(a["labels"]["alertname"] == "GoldStale" for a in alerts),
    }


def spark_batches(windows: list[tuple[float, float]]) -> dict:
    """Duration of the Spark batches that carried data (the players query), sampled every 15 s while replays ran.
    Spark's own latency metric also counts the empty triggers between replays (a few ms each): not used."""
    return br.percentiles(
        [
            v
            for t0, t1 in windows
            for v in prom_range('football_spark_batch_duration_seconds{query="players-5min"}', t0, t1)
        ]
    )


def last_fix() -> tuple[str, float] | None:
    """The newest commit that fixed a real failure: the fix_commit entries of docs/quality_evidence.yml, by git date."""
    import yaml

    evidence = yaml.safe_load((ROOT / "docs" / "quality_evidence.yml").read_text(encoding="utf-8")) or {}
    commits = {c["fix_commit"] for c in evidence.get("caught", []) if c.get("fix_commit")}
    dated = [
        (
            c,
            float(
                subprocess.run(
                    ["git", "log", "-1", "--format=%ct", c], cwd=ROOT, capture_output=True, text=True, check=True
                ).stdout
            ),
        )
        for c in commits
    ]
    return max(dated, key=lambda cd: cd[1]) if dated else None


def success(runs: list[dict]) -> float | None:
    return sum(r["status"] == "SUCCESS" for r in runs) / len(runs) if runs else None


def reliability() -> dict:
    """Over 7 days: every finished run, and the normal ones (no purpose tag); and the normal ones since the last fix."""
    after = time.time() - 7 * 24 * 3600
    runs = gql(
        f"{{ runsOrError(filter: {{createdAfter: {after}}}, limit: 500) {{ ... on Runs {{ results {{ status "
        "startTime tags { key value } stepStats { attempts { startTime } } } } } }"
    )["runsOrError"]["results"]
    done = [r for r in runs if r["status"] in ("SUCCESS", "FAILURE")]
    normal = [r for r in done if not any(t["key"] == "purpose" for t in r["tags"])]
    retries = [sum(max(0, len(s["attempts"]) - 1) for s in r["stepStats"]) for r in runs]
    fix = last_fix()
    since = [r for r in normal if fix and (r["startTime"] or 0) >= fix[1]]
    return {
        "runs": len(done),
        "on_purpose": len(done) - len(normal),
        "success_raw": success(done),
        "success_slo": success(normal),
        "since_fix": {
            "commit": fix[0] if fix else None,
            "at": fix[1] if fix else None,
            "runs": len(since),
            "success": success(since),
        },
        "retries": sum(retries),
        "runs_with_retries": sum(n > 0 for n in retries),
    }


# ---------------------------------------------------------------- main


def preflight() -> None:
    http_json(f"{PROMETHEUS}/api/v1/status/buildinfo")
    gql("{ version }")
    names = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, check=True
    ).stdout.split()
    missing = [
        n
        for n in ("streaming-5min", "football-platform-bronze-writer-1", "football-platform-pipeline-exporter-1")
        if n not in names
    ]
    if missing:
        raise SystemExit(f"not running: {missing} (make streaming, make up, make monitoring)")
    for m in ("m001", "m002", "m003", "m004"):
        if not (ROOT / "data" / "prepared" / m).exists():
            raise SystemExit(f"data/prepared/{m} missing: make data")
    app = prom_at('up{job="live_app"}', time.time())
    if app != 1:  # the Live page's consumer and its metrics start with the first visit of the app
        raise SystemExit("the app's live metrics are not up: open http://localhost:8501 once, then run again")


def machine() -> dict:
    cpu = next(x for x in Path("/proc/cpuinfo").read_text().splitlines() if x.startswith("model name")).split(":")[1]
    mem = next(x for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemTotal")).split()[1]
    return {"cpu": cpu.strip(), "threads": os.cpu_count(), "ram_gib": int(mem) / 2**20}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    preflight()
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    probe = Probe()
    sampler = Sampler(probe)
    probe.start()
    sampler.start()
    probe.ready.wait(30)
    time.sleep(5)
    speed_rows, fresh = speeds(probe, sampler)
    sensor(False)
    try:
        levels = load(probe, sampler)
        restarts = recovery(probe, sampler) if not sampler.danger else []
    finally:
        try:
            skip_paused_replays()
        finally:
            sensor(True)  # whatever happened above
    latest = {m: r for lv in levels for m, r in lv["replays"].items()}
    final = rebuild(latest)
    probe.stop_event.set()
    sampler.stop_event.set()
    ended = time.time()
    results = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": commit,
        "machine": machine(),
        "speeds": speed_rows,
        "freshness": fresh,
        "load": levels,
        "recovery": restarts,
        "final_check": final,
        "safety": {"stopped": sampler.danger is not None, "reason": sampler.danger, "thresholds": SAFETY},
        "spark": {
            "batch_s": spark_batches([(s["t0"], s["t1"]) for s in speed_rows] + [(lv["t0"], lv["t1"]) for lv in levels])
        },
        "stack_peak_mib": (
            prom_at(
                f"max_over_time(sum(container_memory_working_set_bytes{{{CONTAINERS}}})[{int(ended - started)}s:15s])",
                ended,
            )
            or 0
        )
        / 2**20,
        "reliability": reliability(),
        "started": started,
        "ended": ended,
    }
    path = OUT / f"{datetime.now(UTC):%Y-%m-%dT%H%M%SZ}.json"
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    log.info("results: %s (%.0f min)", path.relative_to(ROOT), (ended - started) / 60)


if __name__ == "__main__":
    main()
