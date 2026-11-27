"""main.py: the MatchLens Control Center (make demo, http://localhost:8000). Read-only views of the platform, and two
actions only: start a replay, stop a replay. The rules are in core.py, the services in services.py.

    uvicorn main:app --host 0.0.0.0 --port 8000      (in app/api, with PYTHONPATH as in its Dockerfile)
"""
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import core
import services
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ingestion import replay_ids

HERE = Path(__file__).resolve().parent
ROOT = services.ROOT


def public(name: str, port: str) -> str:
    """The address a browser on this machine uses for a tool (its port on 127.0.0.1)."""
    return os.getenv(f"{name.upper()}_URL_PUBLIC", f"http://localhost:{os.getenv(port, '')}").rstrip("/")


BASE = {"app": public("app", "APP_PORT"), "grafana": public("grafana", "GRAFANA_PORT"),
        "kafka_ui": public("kafka_ui", "KAFKA_UI_PORT"), "spark_master": public("spark_master", "SPARK_MASTER_UI_PORT"),
        "spark_driver": public("spark_driver", "SPARK_DRIVER_UI_PORT"), "minio": public("minio", "MINIO_CONSOLE_PORT"),
        "dagster": public("dagster", "DAGSTER_PORT"), "prometheus": public("prometheus", "PROMETHEUS_PORT"),
        "alertmanager": public("alertmanager", "ALERTMANAGER_PORT")}

prom = services.Prometheus()
replays = services.Replays()
watch = services.KafkaWatch()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("CONTROL_CENTER_WATCH", "1") == "1":       # tests run without Kafka
        watch.start()
    yield


app = FastAPI(title="MatchLens Control Center", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/logo.svg")
def logo() -> FileResponse:
    return FileResponse(ROOT / "app" / "streamlit" / "assets" / "matchlens-logo.svg", media_type="image/svg+xml")


def prepared(match_id: str) -> bool:
    return (ROOT / "data" / "prepared" / match_id / "manifest.json").exists()


@app.get("/api/config")
def config() -> dict:
    """The public addresses of the tools, for the diagram's pictures."""
    return {"base": BASE, "max_running": core.MAX_RUNNING, "max_speed": core.MAX_SPEED}


@app.get("/api/matches")
def matches() -> list[dict]:
    out = []
    for m in services.gold_matches().values():
        goal = core.progress(m, m.first_goal_ts)["clock"] if m.first_goal_ts is not None else None
        out.append({"match_id": m.match_id, "label": m.label, "prepared": prepared(m.match_id), "first_goal": goal})
    return out


def values() -> dict:
    """What the status lights need, read once per refresh."""
    now = time.time()
    soda = prom.by('sum by (layer) (football_soda_checks{result!~"pass|warn"}) or '
                   'sum by (layer) (football_soda_checks) * 0', "layer")
    seen = prom.by("max by (name) (container_last_seen)", "name")
    spark_last = prom.value("max(football_spark_query_reported_timestamp_seconds)")
    return {"prepared_matches": sum(prepared(m) for m in ("m001", "m002", "m003", "m004")),
            "replays_running": len(replays.running()),
            "kafka_up": prom.value('probe_success{service="kafka"}'),
            "spark_report_age_s": now - spark_last if spark_last else None,
            "streaming_up": "streaming-5min" in seen,
            "app_up": prom.value('probe_success{service="app"}'),
            "live_up": prom.value('up{job="live_app"}'),
            "minio_up": prom.value('probe_success{service="minio"}'),
            "bronze_writer_up": "football-platform-bronze-writer-1" in seen,
            "soda_failed": soda, "freshness_max_s": prom.value("max(football_gold_freshness_seconds)"),
            "dagster_up": prom.value('probe_success{service="dagster"}'),
            "runs_failed_latest": prom.value("sum(football_dagster_latest_run_failed)"),
            "prometheus_up": prom.value('up{job="prometheus"}')}


@app.get("/api/status")
def status() -> dict:
    v = values()
    lib = services.gold_matches()
    plays = []
    for match_id, r in replays.snapshot().items():
        m = lib.get(match_id)
        partial = replay_ids.is_partial(r["replay_id"])
        plays.append({**r, "match_id": match_id, "label": m.label if m else match_id, "partial": partial,
                      "progress": core.progress(m, watch.last(r["replay_id"])) if m else None,
                      "messages_per_s": watch.rate(r["replay_id"]),
                      "pipeline": services.replay_run(r["replay_id"]) if r["finished"] and not partial else None,
                      "live_url": f"{BASE['app']}/live_match?match={match_id}"})
    runs = services.running_pipeline_runs()
    return {"lights": core.box_status(v), "warnings": core.warnings(v), "replays": plays, "pipeline_runs": runs,
            "live_moving": any(p["running"] for p in plays), "stored_moving": bool(runs), "at": time.time()}


@app.get("/api/box/{key}")
def box(key: str) -> dict:
    if key not in core.ROLES:
        raise HTTPException(404, "no such box")
    title, role = core.ROLES[key]
    numbers = [{"label": label, "value": core.fmt(prom.value(expr), kind)} for label, expr, kind in core.NUMBERS[key]]
    if key == "skillcorner":
        numbers = [{"label": "matches prepared", "value": str(values()["prepared_matches"])}]
    if key in ("producer", "control"):
        numbers.append({"label": "replays playing", "value": f"{len(replays.running())} of {core.MAX_RUNNING}"})
    return {"key": key, "title": title, "role": role, "numbers": numbers, "links": core.links(BASE)[key]}


@app.get("/api/containers")
def containers() -> list[dict]:
    names = 'name=~"football-platform-.+|streaming-5min"'
    return core.containers(
        cpu=prom.by(f"sum by (name) (rate(container_cpu_usage_seconds_total{{{names}}}[1m]))", "name"),
        memory=prom.by(f"max by (name) (container_memory_working_set_bytes{{{names}}})", "name"),
        limit=prom.by(f"max by (name) (container_spec_memory_limit_bytes{{{names}}})", "name"),
        started=prom.by(f"max by (name) (container_start_time_seconds{{{names}}})", "name"), now=time.time())


@app.get("/api/performance")
def performance() -> dict:
    import benchmark_report as br

    import quality

    files = sorted(p for p in (ROOT / "data" / "benchmark").glob("*.json") if p.name != "current.json")
    results = json.loads(files[-1].read_text(encoding="utf-8")) if files else None
    soda = {layer: json.loads((ROOT / "data" / "soda" / f"{layer}.json").read_text(encoding="utf-8"))
            for layer in ("silver", "gold") if (ROOT / "data" / "soda" / f"{layer}.json").exists()}
    mapping = yaml.safe_load((ROOT / "soda" / "dimensions.yml").read_text(encoding="utf-8")) or {}
    checks = quality.checks_table(soda, mapping)
    panel = core.performance(results, br.slo_verdicts(results) if results else [],
                             (int(len(checks) - len(quality.failed(checks))), int(len(checks))), goal_minutes(quality),
                             last_check(soda))
    panel["now"] = [{"title": t, "value": core.fmt(prom.value(e), k)} for t, e, k in (
        ("Live delay p95", "slo:live_delay_p95_seconds:7d", "s"),
        ("Slowest Gold after the whistle", "slo:gold_freshness_seconds:max", "s"),
        ("Run success (normal runs)", "slo:run_success_ratio:7d", "pct"),
        ("Blocking checks passed", "slo:blocking_checks_pass_ratio", "pct"),
        ("App up", "slo:app_up_ratio:7d", "pct"))]
    return panel


def last_check(results: dict) -> str | None:
    """When the last Soda run finished, as the Data quality page writes it."""
    from datetime import UTC, datetime

    times = [r["finished_at_utc"] for r in results.values() if r.get("finished_at_utc")]
    return datetime.fromisoformat(max(times).replace("Z", "+00:00")).astimezone(UTC).strftime("%d %b %Y %H:%M UTC") \
        if times else None


def goal_minutes(quality) -> tuple[int, int]:
    """Goals whose minute is exactly one of the official sources' (Data quality page, accuracy)."""
    import duckdb

    external = yaml.safe_load((ROOT / "docs" / "external_checks.yml").read_text(encoding="utf-8"))
    con = duckdb.connect(str(services.GOLD), read_only=True)
    try:
        frames = {t: con.execute(f"select * from {t}").df() for t in
                  ("gold_events", "gold_match_library", "gold_team_profile")}
    finally:
        con.close()
    acc = quality.accuracy(external, frames["gold_events"], frames["gold_match_library"], frames["gold_team_profile"])
    goals = acc[acc.what.str.startswith("goal")]
    return int((goals.status == quality.GREEN).sum()), int(len(goals))


class Start(BaseModel):
    match: str
    speed: int | float | str
    start: str = "kickoff"


class Stop(BaseModel):
    match: str


@app.post("/api/replay/start")
def replay_start(body: Start) -> dict:
    m = services.gold_matches().get(body.match)
    try:
        replay = replays.start(m, body.speed, body.start, prepared(m.match_id) if m else False)
    except core.Refused as why:
        raise HTTPException(409, str(why)) from None
    return {"match": body.match, "replay_id": replay}


@app.post("/api/replay/stop")
def replay_stop(body: Stop) -> dict:
    if not replays.stop(body.match):
        raise HTTPException(404, f"{body.match} is not playing")
    return {"match": body.match, "stopped": True}
