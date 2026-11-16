"""The final whistle of a replay starts the chain of its match; every finished run is logged for the dashboard.

replay_end    reads foot-matches (small: whole topic) and the foot-tracking messages that arrived since the last tick
              (offsets kept in the sensor cursor). A replay that reached its last second starts `match_pipeline` for its
              match; the run key is the replay_id, so one replay never starts two runs.
run_log       after each run of the pipeline: data/pipeline/runs.json (latest runs, the outcome of every step and check)
              and data/pipeline/graph.json (the asset graph), read by the Pipeline & lineage page.
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import dagster as dg
from confluent_kafka import Consumer, TopicPartition

from football_platform.assets import BOOTSTRAP, matches, soda_gold, soda_silver
from football_platform.replays import finished, replay_ends

REPLAY_HEADER = "replay_id"
MATCHES_TOPIC = os.getenv("KAFKA_TOPIC_MATCHES", "foot-matches")
TRACKING_TOPIC = os.getenv("KAFKA_TOPIC_TRACKING", "foot-tracking")
MAX_MESSAGES = 500_000            # one tick reads at most this much tracking; the rest waits for the next tick
PIPELINE_OUT = Path(os.getenv("PIPELINE_OUT_DIR", Path(__file__).resolve().parents[2] / "data" / "pipeline"))
KEEP_RUNS = 30

match_pipeline = dg.define_asset_job("match_pipeline", selection=dg.AssetSelection.all(), partitions_def=matches,
                                     description="bronze -> silver -> Soda Silver -> Gold -> Soda Gold -> report")
nightly_quality = dg.define_asset_job("nightly_quality", selection=dg.AssetSelection.checks(soda_silver, soda_gold),
                                      description="the Soda checks of Silver and Gold on the stored data, nothing rebuilt")


def _replay_id(msg) -> str | None:
    return next((v.decode() for k, v in msg.headers() or [] if k == REPLAY_HEADER), None)


def read(consumer: Consumer, start: dict[TopicPartition, int], limit: int):
    """The messages from `start` up to the end offsets seen now; returns (messages, next offsets)."""
    ends = {tp: consumer.get_watermark_offsets(tp, timeout=10)[1] for tp in start}
    todo = [TopicPartition(tp.topic, tp.partition, off) for tp, off in start.items() if off < ends[tp]]
    nxt = dict(start)
    out = []
    if not todo:
        return out, nxt
    consumer.assign(todo)
    while len(out) < limit and any(nxt[tp] < ends[tp] for tp in nxt):
        batch = consumer.consume(10_000, timeout=2.0)
        if not batch:
            break
        for msg in batch:
            if msg.error():
                continue
            tp = TopicPartition(msg.topic(), msg.partition())
            nxt[tp] = msg.offset() + 1
            out.append(msg)
    return out, nxt


@dg.sensor(job=match_pipeline, minimum_interval_seconds=15, default_status=dg.DefaultSensorStatus.RUNNING)
def replay_end(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    consumer = Consumer({"bootstrap.servers": BOOTSTRAP, "group.id": "dagster-replay-end", "enable.auto.commit": False,
                         "log_level": 3})
    try:
        meta = consumer.list_topics(timeout=10).topics
        whole = {}
        for p in meta[MATCHES_TOPIC].partitions:      # from the oldest message Kafka still keeps
            tp = TopicPartition(MATCHES_TOPIC, p)
            whole[tp] = consumer.get_watermark_offsets(tp, timeout=10)[0]
        ends = replay_ends((_replay_id(m), json.loads(m.value())) for m in read(consumer, whole, 100_000)[0])
        saved = json.loads(context.cursor) if context.cursor else {}
        start = {}
        for p in meta[TRACKING_TOPIC].partitions:
            tp = TopicPartition(TRACKING_TOPIC, p)
            # first tick: start at the end, an old replay is not a new final whistle
            start[tp] = saved[str(p)] if str(p) in saved else consumer.get_watermark_offsets(tp, timeout=10)[1]
        msgs, nxt = read(consumer, start, MAX_MESSAGES)
        done = finished(ends, ((_replay_id(m), json.loads(m.value())["ts"]) for m in msgs))
    finally:
        consumer.close()
    context.update_cursor(json.dumps({str(tp.partition): off for tp, off in nxt.items()}))
    known = set(context.instance.get_dynamic_partitions(matches.name))
    new = sorted({match_id for match_id, _ in ends.values()} - known)
    runs = [dg.RunRequest(run_key=rid, partition_key=ends[rid][0], tags={"replay_id": rid}) for rid in sorted(done)]
    if runs:
        context.log.info("final whistle: " + ", ".join(sorted(done)))
    return dg.SensorResult(run_requests=runs,
                           dynamic_partitions_requests=[matches.build_add_request(new)] if new else None)


nightly = dg.ScheduleDefinition(job=nightly_quality, cron_schedule="0 3 * * *", execution_timezone="UTC",
                                default_status=dg.DefaultScheduleStatus.RUNNING)


def _check_outcomes(instance, run_id: str) -> list[dict]:
    records = instance.get_records_for_run(run_id, of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION).records
    out = []
    for r in records:
        ev = r.event_log_entry.dagster_event.event_specific_data
        out.append({"asset": ev.asset_key.to_user_string(), "check": ev.check_name, "passed": ev.passed})
    return out


def run_entry(instance, run) -> dict:
    """One finished run: status, partition, replay, and the outcome of each step and check."""
    stats = instance.get_run_step_stats(run.run_id)
    when = [s.start_time for s in stats if s.start_time] + [s.end_time for s in stats if s.end_time]
    ran = {s.step_key for s in stats}
    planned = instance.get_execution_plan_snapshot(run.execution_plan_snapshot_id).step_keys_to_execute or []
    # a step after a failure never starts and has no stats: it is the "not built" part of the run
    never = [{"step": k, "status": "SKIPPED", "start": None, "end": None} for k in planned if k not in ran]
    return {"run_id": run.run_id, "job": run.job_name, "status": run.status.value,
            "match_id": run.tags.get("dagster/partition"), "replay_id": run.tags.get("replay_id"),
            "trigger": "sensor" if run.tags.get("dagster/sensor_name") else
            "schedule" if run.tags.get("dagster/schedule_name") else "manual",
            "started": min(when, default=None), "ended": max(when, default=None),
            "steps": [{"step": s.step_key, "status": s.status.value if s.status else None, "start": s.start_time,
                       "end": s.end_time} for s in stats] + never,
            "checks": _check_outcomes(instance, run.run_id)}


def asset_graph(defs: dg.Definitions) -> dict:
    graph = defs.resolve_asset_graph()
    nodes = []
    for key in sorted(graph.get_all_asset_keys(), key=lambda k: k.to_user_string()):
        node = graph.get(key)
        nodes.append({"key": key.to_user_string(), "group": node.group_name,
                      "deps": sorted(p.to_user_string() for p in node.parent_keys),
                      "checks": sorted(c.name for c in node.check_keys)})
    return {"written_at": datetime.now(UTC).isoformat(timespec="seconds"), "assets": nodes}


def _write(name: str, payload) -> None:
    PIPELINE_OUT.mkdir(parents=True, exist_ok=True)
    tmp = PIPELINE_OUT / f".{name}.tmp"
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(PIPELINE_OUT / name)          # the dashboard never reads a half-written file


def log_run(context: dg.RunStatusSensorContext) -> None:
    from football_platform.definitions import defs

    path = PIPELINE_OUT / "runs.json"
    runs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entry = run_entry(context.instance, context.dagster_run)
    runs = [entry] + [r for r in runs if r["run_id"] != entry["run_id"]]
    _write("runs.json", runs[:KEEP_RUNS])
    _write("graph.json", asset_graph(defs))


@dg.run_status_sensor(run_status=dg.DagsterRunStatus.SUCCESS, monitored_jobs=[match_pipeline, nightly_quality],
                      default_status=dg.DefaultSensorStatus.RUNNING)
def run_log_success(context: dg.RunStatusSensorContext) -> None:
    log_run(context)


@dg.run_status_sensor(run_status=dg.DagsterRunStatus.FAILURE, monitored_jobs=[match_pipeline, nightly_quality],
                      default_status=dg.DefaultSensorStatus.RUNNING)
def run_log_failure(context: dg.RunStatusSensorContext) -> None:
    log_run(context)
