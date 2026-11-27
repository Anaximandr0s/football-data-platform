"""pipeline_exporter.py: the state of the data pipeline as Prometheus metrics, rebuilt at every scrape.

Sources: Dagster (GraphQL: runs, steps, last success per match), dbt (target/run_results.json), Soda (data/soda/*.json
with the dimension of each check from soda/dimensions.yml), the Spark streaming progress file, and Gold freshness per
match with the Data quality page's own rule (quality.freshness). Pure functions turn each source into samples; only
`fetch_runs`, `read_json` and `main` touch the network or the disk."""

import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import NamedTuple

import yaml
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily

import quality

log = logging.getLogger("pipeline_exporter")

ROOT = Path(os.getenv("PROJECT_ROOT", "/app"))
DAGSTER_GRAPHQL = os.getenv("DAGSTER_GRAPHQL", "http://dagster-webserver:3000/graphql")
WINDOW_S = 7 * 24 * 3600  # the Prometheus retention: runs older than this are not counted
RUNS_QUERY = """query ($after: Float) { runsOrError(filter: {createdAfter: $after}, limit: 500) {
  __typename ... on Runs { results { runId jobName status startTime endTime tags { key value }
  stepStats { stepKey status startTime endTime } } } ... on PythonError { message } } }"""
FINISHED = {"SUCCESS", "FAILURE", "CANCELED"}

HELP = {
    "football_exporter_source_up": "1 when the exporter could read this source at the last scrape",
    "football_dagster_up": "1 when Dagster answered the last GraphQL query",
    "football_dagster_runs": "Dagster runs started in the last 7 days, by job, status and whether they were started "
    "on purpose for a test (tag purpose: damaged-data demo, benchmark)",
    "football_benchmark_scenario": "1 while this scenario of make benchmark runs (Grafana annotations)",
    "football_dagster_latest_run_failed": "1 when the latest finished run of this job and match failed",
    "football_dagster_step_duration_seconds": "Duration of each step in the latest run that finished it",
    "football_dagster_last_success_timestamp_seconds": "End of the latest successful match_pipeline run, per match",
    "football_gold_freshness_seconds": "Seconds from the final whistle of the latest replay to Gold ready, per match",
    "football_gold_waiting_seconds": "Seconds since the final whistle of the latest replay while Gold is not ready yet",
    "football_dbt_tests": "dbt tests of the last dbt build, by status",
    "football_dbt_test_failed": "1 for each dbt test that did not pass in the last dbt build",
    "football_dbt_results_timestamp_seconds": "When the last dbt build wrote its results",
    "football_soda_checks": "Soda checks of the last run per layer, by dimension and result",
    "football_soda_check_failed": "1 for each Soda check that failed in the last run of its layer",
    "football_soda_results_timestamp_seconds": "When the last Soda run of each layer wrote its results",
    "football_spark_query_reported_timestamp_seconds": "When Spark last reported on this streaming query",
    "football_spark_query_running": "1 while the streaming query runs",
    "football_spark_offsets_behind_latest": "Kafka offsets the streaming query is behind the latest ones",
    "football_spark_input_rows_per_second": "Rows per second arriving in the last batch",
    "football_spark_processed_rows_per_second": "Rows per second processed in the last batch",
    "football_spark_batch_duration_seconds": "Duration of the last micro-batch",
}


class Sample(NamedTuple):
    name: str
    labels: dict
    value: float


# ---------------------------------------------------------------- Dagster


def runs_from_graphql(results: list[dict]) -> list[dict]:
    """GraphQL runs in the shape Dagster writes to data/pipeline/runs.json (football_platform.sensors.run_entry), so
    quality.freshness reads both the same way."""
    out = []
    for r in results:
        tags = {t["key"]: t["value"] for t in r["tags"]}
        steps = [
            {"step": s["stepKey"], "status": s["status"], "start": s["startTime"], "end": s["endTime"]}
            for s in r["stepStats"]
        ]
        starts = [s["start"] for s in steps if s["start"]]
        out.append(
            {
                "run_id": r["runId"],
                "job": r["jobName"],
                "status": r["status"],
                "match_id": tags.get("dagster/partition"),
                "replay_id": tags.get("replay_id")
                or (tags.get("dagster/run_key") if tags.get("dagster/sensor_name") else None),
                "started": min(starts, default=r["startTime"]),
                "ended": r["endTime"],
                "steps": steps,
                "purpose": tags.get("purpose", ""),
            }
        )
    return out


def dagster_samples(runs: list[dict], now: float) -> list[Sample]:
    out = []
    counts: dict[tuple, int] = {}
    for r in runs:
        key = (r["job"], r["status"], "true" if r.get("purpose") else "false")
        counts[key] = counts.get(key, 0) + 1
    out += [
        Sample("football_dagster_runs", {"dagster_job": j, "status": s, "on_purpose": p}, n)
        for (j, s, p), n in sorted(counts.items())
    ]

    done = sorted((r for r in runs if r["status"] in FINISHED and r["ended"]), key=lambda r: r["ended"])
    latest = {(r["job"], r["match_id"] or ""): r for r in done}  # the last one wins
    out += [
        Sample(
            "football_dagster_latest_run_failed",
            {"dagster_job": j, "match_id": m, "run_id": r["run_id"]},
            float(r["status"] == "FAILURE"),
        )
        for (j, m), r in sorted(latest.items())
    ]

    steps = {}
    for r in done:
        for s in r["steps"]:
            if s["start"] and s["end"]:
                steps[(r["job"], s["step"])] = s["end"] - s["start"]
    out += [
        Sample("football_dagster_step_duration_seconds", {"dagster_job": j, "step": s}, d)
        for (j, s), d in sorted(steps.items())
    ]

    success = {
        r["match_id"]: r["ended"]
        for r in done
        if r["job"] == "match_pipeline" and r["status"] == "SUCCESS" and r["match_id"]
    }
    out += [
        Sample("football_dagster_last_success_timestamp_seconds", {"match_id": m}, t)
        for m, t in sorted(success.items())
    ]
    return out


def freshness_samples(runs: list[dict], now: float) -> list[Sample]:
    """Per match, its latest replay: how long Gold took to be ready, or how long it has been waiting. A run still queued
    has no start (the whistle, for quality.freshness) yet: it counts once it starts."""
    runs = [r for r in runs if r["started"] is not None]
    out = []
    for match in sorted({r["match_id"] for r in runs if r.get("replay_id") and r.get("match_id")}):
        _, seconds, replay = quality.freshness(runs, match)
        labels = {"match_id": match, "replay_id": replay}
        if seconds is not None:
            out += [
                Sample("football_gold_freshness_seconds", labels, seconds),
                Sample("football_gold_waiting_seconds", labels, 0.0),
            ]
        else:
            whistle = max(
                (r for r in runs if r["match_id"] == match and r.get("replay_id")), key=lambda r: r["replay_id"]
            )["started"]
            out.append(Sample("football_gold_waiting_seconds", labels, now - whistle))
    return out


# ---------------------------------------------------------------- dbt and Soda


def dbt_test_name(unique_id: str) -> str:
    """test.football.not_null_gold_shots_match_id.5f3a -> not_null_gold_shots_match_id"""
    parts = unique_id.split(".")
    return parts[2] if len(parts) > 2 else unique_id


def dbt_samples(run_results: dict | None, written_at: float | None) -> list[Sample]:
    if not run_results:
        return []
    tests = [r for r in run_results["results"] if r["unique_id"].startswith("test.")]
    counts: dict[str, int] = {}
    for t in tests:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    out = [Sample("football_dbt_tests", {"status": s}, n) for s, n in sorted(counts.items())]
    out += [
        Sample("football_dbt_test_failed", {"test": dbt_test_name(t["unique_id"])}, 1.0)
        for t in tests
        if t["status"] != "pass"
    ]
    if written_at:
        out.append(Sample("football_dbt_results_timestamp_seconds", {}, written_at))
    return out


def soda_samples(results: dict[str, dict], mapping: dict, written_at: dict[str, float]) -> list[Sample]:
    """results: layer -> the Soda JSON of its last run (normal or damaged-data demo, whichever is newer)."""
    checks = quality.checks_table(results, mapping)
    out = []
    for (layer, dim, result), n in checks.groupby(["layer", "dimension", "result"]).size().items():
        out.append(Sample("football_soda_checks", {"layer": layer, "dimension": dim, "result": result}, float(n)))
    for c in quality.failed(checks).itertuples():
        out.append(
            Sample(
                "football_soda_check_failed",
                {"layer": c.layer, "dimension": c.dimension, "table": c.table, "check": c.check},
                1.0,
            )
        )
    out += [Sample("football_soda_results_timestamp_seconds", {"layer": layer}, t) for layer, t in written_at.items()]
    return out


def newest_soda_files(folder: Path) -> dict[str, Path]:
    """Per layer, the newest of <layer>.json (make soda, Dagster) and <layer>-damaged.json (the damaged-data demo)."""
    out = {}
    for layer in ("silver", "gold"):
        files = [p for p in (folder / f"{layer}.json", folder / f"{layer}-damaged.json") if p.exists()]
        if files:
            out[layer] = max(files, key=lambda p: p.stat().st_mtime)
    return out


# ---------------------------------------------------------------- Spark streaming


def spark_samples(progress: dict | None) -> list[Sample]:
    out = []
    for query, q in sorted((progress or {}).items()):
        labels = {"query": query}
        out += [
            Sample("football_spark_query_reported_timestamp_seconds", labels, q["reported_at"]),
            Sample("football_spark_query_running", labels, float(q.get("running", False))),
        ]
        for key, name, scale in (
            ("offsets_behind_latest", "football_spark_offsets_behind_latest", 1),
            ("input_rows_per_second", "football_spark_input_rows_per_second", 1),
            ("processed_rows_per_second", "football_spark_processed_rows_per_second", 1),
            ("batch_duration_ms", "football_spark_batch_duration_seconds", 1000),
        ):
            if q.get(key) is not None:
                out.append(Sample(name, labels, q[key] / scale))
    return out


# ---------------------------------------------------------------- the edges: network, disk, HTTP


def fetch_runs(url: str, now: float) -> list[dict]:
    body = json.dumps({"query": RUNS_QUERY, "variables": {"after": now - WINDOW_S}}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        answer = json.loads(resp.read())["data"]["runsOrError"]
    if answer["__typename"] != "Runs":
        raise RuntimeError(f"Dagster GraphQL: {answer.get('message', answer['__typename'])}")
    return runs_from_graphql(answer["results"])


def read_json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def dagster_source(now: float) -> list[Sample]:
    try:
        runs = fetch_runs(DAGSTER_GRAPHQL, now)
    except (OSError, KeyError, RuntimeError) as exc:  # Dagster stopped or restarting: said by football_dagster_up
        log.warning("dagster: %s", exc)
        return [Sample("football_dagster_up", {}, 0.0)]
    return [Sample("football_dagster_up", {}, 1.0), *dagster_samples(runs, now), *freshness_samples(runs, now)]


def dbt_source(now: float) -> list[Sample]:
    path = ROOT / "dbt" / "target" / "run_results.json"
    return dbt_samples(read_json(path), path.stat().st_mtime if path.exists() else None)


def soda_source(now: float) -> list[Sample]:
    files = newest_soda_files(ROOT / "data" / "soda")
    mapping = yaml.safe_load((ROOT / "soda" / "dimensions.yml").read_text(encoding="utf-8")) or {}
    return soda_samples(
        {layer: read_json(p) for layer, p in files.items()},
        mapping,
        {layer: p.stat().st_mtime for layer, p in files.items()},
    )


def spark_source(now: float) -> list[Sample]:
    return spark_samples(read_json(ROOT / "data" / "streaming" / "progress.json"))


def benchmark_source(now: float) -> list[Sample]:
    current = read_json(ROOT / "data" / "benchmark" / "current.json")  # written by scripts/benchmark.py
    return [Sample("football_benchmark_scenario", {"scenario": current["scenario"]}, 1.0)] if current else []


SOURCES = {
    "dagster": dagster_source,
    "dbt": dbt_source,
    "soda": soda_source,
    "spark": spark_source,
    "benchmark": benchmark_source,
}


def collect_samples(now: float) -> list[Sample]:
    """Every source on its own: one that fails is logged with its traceback and reported as down (an alert), the others
    are still served. Without this, one bad file would empty the whole scrape and every alert would look resolved."""
    out = []
    for name, source in SOURCES.items():
        try:
            samples = source(now)
        except Exception:
            log.exception("source %s failed", name)
            out.append(Sample("football_exporter_source_up", {"source": name}, 0.0))
            continue
        out += [Sample("football_exporter_source_up", {"source": name}, 1.0), *samples]
    return out


class Collector:
    def collect(self):
        families: dict[str, GaugeMetricFamily] = {}
        for s in collect_samples(time.time()):
            if s.name not in families:
                families[s.name] = GaugeMetricFamily(s.name, HELP[s.name], labels=list(s.labels))
            families[s.name].add_metric([str(v) for v in s.labels.values()], s.value)
        yield from families.values()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    REGISTRY.register(Collector())
    port = int(os.getenv("EXPORTER_PORT", "9110"))
    start_http_server(port)
    log.info("serving on :%s", port)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
