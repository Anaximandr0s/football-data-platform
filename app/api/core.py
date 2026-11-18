"""core.py: the Control Center's rules, as pure functions (no network, no disk): which replay may start, where it starts,
how far it is, which box is green, where each button leads, and the numbers of the performance panel."""
import re
from dataclasses import dataclass

import clock  # app/streamlit/clock.py: the football clock fans see on TV

PRESET_SPEEDS = (1, 5, 10)
MAX_SPEED = 60
MAX_RUNNING = 2                      # replays at the same time, all matches together
GOAL_LEAD_S = 30


class Refused(ValueError):
    """A replay that may not start: the message says why, in plain words."""


@dataclass(frozen=True)
class Match:
    match_id: str
    label: str                       # "Perth Glory 1-3 Brisbane Roar · 15 Mar 2025"
    p1_start: int
    p1_end: int
    p2_start: int
    p2_end: int
    first_goal_ts: int | None        # the second the ball was in the goal (gold_events.goal_ts)


# ---------------------------------------------------------------- starting a replay

def start_second(m: Match, start: str) -> int:
    """The match second a replay starts from: "kickoff", "goal" (30 s before the first goal, ball in the goal) or a
    TV clock "mm:ss" (00:00 to 45:00 in the first half, 45:00 to 90:00 from the second kick-off)."""
    if start == "kickoff":
        return m.p1_start
    if start == "goal":
        if m.first_goal_ts is None:
            raise Refused(f"{m.label}: no goal in this match")
        return max(m.p1_start, m.first_goal_ts - GOAL_LEAD_S)
    found = re.fullmatch(r"(\d{1,2}):([0-5]\d)", start.strip())
    if not found:
        raise Refused("start: kick-off, 30 s before the first goal, or a clock like 47:30")
    seconds = int(found.group(1)) * 60 + int(found.group(2))
    if seconds < 45 * 60:
        ts = m.p1_start + seconds
    elif seconds <= 90 * 60:
        ts = m.p2_start + seconds - 45 * 60
    else:
        raise Refused("the clock goes from 00:00 to 90:00")
    if ts > m.p2_end:
        raise Refused(f"{m.label} ends before {start}")
    return ts


def check_start(m: Match | None, speed, prepared: bool, running: dict[str, str]) -> int:
    """The whitelist of POST /api/replay/start. running: match_id -> replay_id of the replays still sending."""
    if m is None:
        raise Refused("unknown match: choose one of the match library")
    if not prepared:
        raise Refused(f"{m.match_id} has no prepared files (make data)")
    if not isinstance(speed, int) or isinstance(speed, bool) or not 1 <= speed <= MAX_SPEED:
        raise Refused(f"speed: a whole number from 1 to {MAX_SPEED}")
    if m.match_id in running:
        raise Refused(f"{m.label} is already playing ({running[m.match_id]}): stop it first")
    if len(running) >= MAX_RUNNING:
        raise Refused(f"{MAX_RUNNING} replays are already playing: stop one first")
    return speed


def progress(m: Match, last_ts: int | None) -> dict:
    """How far a replay is, from the last match second actually sent to Kafka (the producer can be slower than its
    target speed): the TV clock and the share of the match."""
    if last_ts is None:
        return {"last_ts": None, "clock": "–", "share": 0.0}
    period = 1 if last_ts < m.p2_start else 2
    share = (last_ts - m.p1_start) / (m.p2_end - m.p1_start) if m.p2_end > m.p1_start else 0.0
    return {"last_ts": last_ts, "clock": clock.running(last_ts, period, m.p1_start, m.p2_start),
            "share": min(1.0, max(0.0, share))}


# ---------------------------------------------------------------- the diagram: status of each box

GREEN, ORANGE, RED, GREY = "green", "orange", "red", "grey"


def box_status(v: dict) -> dict[str, str]:
    """v: the values read from Prometheus and the replays (main.py, `status`). One light per box of the diagram."""
    def up(x) -> str:
        return GREY if x is None else GREEN if x >= 1 else RED

    spark_age = v.get("spark_report_age_s")
    soda = v.get("soda_failed") or {}
    return {
        "skillcorner": GREEN if v.get("prepared_matches") else RED,
        "producer": GREEN if v.get("replays_running") else GREY,
        "kafka": up(v.get("kafka_up")),
        "spark": GREY if spark_age is None else GREEN if spark_age < 60 else RED,
        "live": up(v.get("app_up")) if v.get("live_up") != 0 else ORANGE,
        "bronze": RED if v.get("minio_up") == 0 else up(v.get("bronze_writer_up")),
        "silver": GREY if "silver" not in soda else GREEN if soda["silver"] == 0 else RED,
        "gold": GREY if "gold" not in soda else RED if soda["gold"] else
        GREEN if (v.get("freshness_max_s") or 0) <= 600 else ORANGE,
        "analysis": up(v.get("app_up")),
        "dagster": RED if v.get("dagster_up") == 0 else RED if v.get("runs_failed_latest") else up(v.get("dagster_up")),
        "monitoring": up(v.get("prometheus_up")),
    }


def warnings(v: dict) -> list[str]:
    """What stops the demo from showing everything, in plain words."""
    out = []
    if not v.get("streaming_up"):
        out.append("The Spark streaming job is not running: the 5-minute statistics will not be computed. Run "
                   "`make streaming`.")
    if not v.get("bronze_writer_up"):
        out.append("The Bronze writer is not running: a replay will not be stored, and Dagster will not rebuild the "
                   "match. Run `make up`.")
    if v.get("kafka_up") == 0:
        out.append("Kafka does not answer: nothing can be played. Run `make up`.")
    if v.get("app_up") == 1 and v.get("live_up") == 0:
        out.append("The Live page has not been opened since the app started: its Kafka reader starts with the first "
                   "visit. Open the Live page once (button of the Live page box).")
    return out


# ---------------------------------------------------------------- buttons to the real tools

def links(base: dict[str, str], match_id: str | None = None) -> dict[str, list[dict]]:
    """Per box, the buttons opening the real UIs. base: public URLs (http://localhost:<port>) by tool."""
    app, m = base["app"], f"match={match_id}" if match_id else ""

    def page(key: str, view: str | None = None) -> str:
        q = "&".join(x for x in (f"view={view}" if view else "", m) if x)
        return f"{app}/{key}" + (f"?{q}" if q else "")

    grafana = base["grafana"]
    return {
        "skillcorner": [{"label": "SkillCorner open data", "url": "https://github.com/SkillCorner/opendata"}],
        "producer": [{"label": "Kafka UI: topics", "url": f"{base['kafka_ui']}/ui/clusters/local/all-topics"}],
        "kafka": [{"label": "Kafka UI: topics", "url": f"{base['kafka_ui']}/ui/clusters/local/all-topics"},
                  {"label": "Kafka UI: consumer groups", "url": f"{base['kafka_ui']}/ui/clusters/local/consumer-groups"},
                  {"label": "Grafana: Streaming", "url": f"{grafana}/d/streaming"}],
        "spark": [{"label": "Spark: streaming job", "url": f"{base['spark_driver']}/StreamingQuery/"},
                  {"label": "Spark: cluster", "url": base["spark_master"]},
                  {"label": "Grafana: Streaming", "url": f"{grafana}/d/streaming"}],
        "live": [{"label": "Live page", "url": page("live_match")},
                 {"label": "Replay page", "url": page("replay")}],
        "bronze": [{"label": "MinIO: bronze bucket", "url": f"{base['minio']}/browser/bronze"},
                   {"label": "Grafana: Infrastructure", "url": f"{grafana}/d/infrastructure"}],
        "silver": [{"label": "MinIO: silver bucket", "url": f"{base['minio']}/browser/silver"},
                   {"label": "Data quality page", "url": page("data_quality")}],
        "gold": [{"label": "MinIO: gold bucket", "url": f"{base['minio']}/browser/gold"},
                 {"label": "Pipeline & lineage page", "url": page("pipeline_lineage")},
                 {"label": "Grafana: Pipeline & data quality", "url": f"{grafana}/d/pipeline"}],
        "analysis": [{"label": "Home", "url": page("")},
                     {"label": "Match library", "url": page("match_library")},
                     {"label": "Match story (fan)", "url": page("match_story", "fan")},
                     {"label": "Team analysis (coach)", "url": page("team_analysis", "coach")},
                     {"label": "Physical & fatigue (coach)", "url": page("physical_fatigue", "coach")},
                     {"label": "Compare matches", "url": page("compare_matches")},
                     {"label": "Data quality", "url": page("data_quality")},
                     {"label": "Sources & limits", "url": page("sources_limits")}],
        "dagster": [{"label": "Dagster: runs", "url": f"{base['dagster']}/runs"},
                    {"label": "Dagster: asset graph", "url": f"{base['dagster']}/asset-groups"},
                    {"label": "Pipeline & lineage page", "url": page("pipeline_lineage")}],
        "monitoring": [{"label": "Grafana: Service levels", "url": f"{grafana}/d/slo"},
                       {"label": "Grafana: Infrastructure", "url": f"{grafana}/d/infrastructure"},
                       {"label": "Grafana: Streaming", "url": f"{grafana}/d/streaming"},
                       {"label": "Grafana: Pipeline & data quality", "url": f"{grafana}/d/pipeline"},
                       {"label": "Prometheus: targets", "url": f"{base['prometheus']}/targets"},
                       {"label": "Alertmanager: alerts", "url": base["alertmanager"]}],
    }


# ---------------------------------------------------------------- containers (cAdvisor, no Docker socket)

EXPECTED = ("kafka", "minio", "bronze-writer", "kafka-ui", "spark-master", "spark-worker", "dagster-webserver",
            "dagster-daemon", "app", "prometheus", "alertmanager", "grafana", "cadvisor", "node-exporter",
            "kafka-exporter", "blackbox", "pipeline-exporter", "control-center")


def short_name(name: str) -> str:
    return name.removeprefix("football-platform-").removesuffix("-1")


def containers(cpu: dict[str, float], memory: dict[str, float], limit: dict[str, float],
               started: dict[str, float], now: float) -> list[dict]:
    """One row per container cAdvisor sees, plus every expected one it does not see (not running)."""
    seen = {short_name(n) for n in memory}
    rows = [{"name": short_name(n), "running": True, "cpu_cores": cpu.get(n, 0.0), "memory_mib": memory[n] / 2**20,
             "limit_mib": limit[n] / 2**20 if limit.get(n) else None,
             "uptime_s": now - started[n] if started.get(n) else None} for n in memory]
    rows += [{"name": e, "running": False, "cpu_cores": None, "memory_mib": None, "limit_mib": None, "uptime_s": None}
             for e in EXPECTED if e not in seen]
    return sorted(rows, key=lambda r: (not r["running"], -(r["memory_mib"] or 0)))


# ---------------------------------------------------------------- performance and quality, in plain words

def performance(results: dict, verdicts: list[dict]) -> list[dict]:
    """The numbers of the last `make benchmark`, each with one line saying what it means."""
    x1 = next(s for s in results["speeds"] if s["speed"] == 1)
    x60 = next(s for s in results["speeds"] if s["speed"] == 60)
    f, load = results["freshness"], results["load"]
    top = load[-1] if load else None
    spark = results["spark"]["batch_s"]
    return [
        {"title": "Live delay", "value": f"{x1['live_delay_ms']['p95'] / 1000:.2f} s",
         "line": "95 % of the positions reach the Live page within this time after they are sent (x1)."},
        {"title": "Final whistle → Gold", "value": f"{f['gold_ready_s'] / 60:.1f} min",
         "line": "After the last second of a replay, the statistics of the match are rebuilt within this time."},
        {"title": "Throughput", "value": f"{x60['kafka_msgs_per_s']['p50']:,.0f} msg/s",
         "line": "Messages per second through Kafka when a match is replayed 60 times faster than real time."},
        {"title": "Load", "value": f"{top['level']} matches" if top else "–",
         "line": "Matches played at once at x60 without any reader falling behind "
                 f"(the slowest needs {max(r['drain_s'] or 0 for r in top['readers'].values()):.0f} s to catch up)."
                 if top else "No load test yet."},
        {"title": "Spark batch", "value": f"{spark['p50']:.1f} s",
         "line": "Time Spark needs for one batch of the 5-minute statistics (it starts a new one every 5 s)."},
        {"title": "Run success", "value": f"{(results['reliability'].get('since_fix') or {}).get('success', 0):.0%}",
         "line": "Pipeline runs that succeeded since the last bug fix (normal runs, tests left out)."},
    ] + [{"title": v["slo"], "value": "PASS" if v["pass"] else "FAIL", "line": f"Measured: {v['measured']}.",
          "pass": v["pass"]} for v in verdicts]


# ---------------------------------------------------------------- the popups: role in our project, live numbers

ROLES = {
    "skillcorner": ("SkillCorner open data", "Real broadcast tracking of four A-League matches (MIT licence): every "
                    "player and the ball, once per second, plus the game events. Converted once into data/prepared."),
    "producer": ("Producer", "Replays a stored match into Kafka as if it were live, second by second, at 1 to 60 times "
                 "real speed. Each replay gets an id (replay_id) carried by every message."),
    "kafka": ("Kafka", "The meeting point: five topics (tracking, ball, events, players, matches) hold every message "
              "for 7 days. Everything downstream reads from here, live or later."),
    "spark": ("Spark Structured Streaming", "Reads the live messages and computes 5- and 15-minute statistics per "
              "player and team (distance, sprints, possession, pressing), written to the topic foot-live-stats."),
    "live": ("Live page", "The match while it is being played: positions, score and clock from Kafka, and the "
             "5-minute statistics from Spark. About half a second behind the producer."),
    "bronze": ("Bronze (MinIO)", "Every message stored as received, one folder per replay: the raw history. Written "
               "by the Bronze writer every 10 s or 5,000 rows."),
    "silver": ("Silver (Iceberg)", "The latest complete replay of each match, cleaned: duplicates removed, both halves "
               "in one direction, impossible speeds removed. Checked by Soda before Gold is built."),
    "gold": ("Gold (dbt + DuckDB)", "The statistics the site shows: 17 tables built by dbt from Silver, tested, and "
             "checked again by Soda. One DuckDB file, also exported to MinIO."),
    "analysis": ("Analysis app", "The MatchLens website: a fan view (story, squad, players) and a coach view (team "
                 "shape, pressing, fatigue, events), with every number explained and its limits stated."),
    "dagster": ("Dagster + Soda", "When a replay reaches its final whistle, Dagster runs its match's chain: Bronze "
                "check, Silver, Soda, Gold, Soda, report. A failed Soda check stops what follows."),
    "monitoring": ("Monitoring", "Prometheus reads every service every 15 s, Grafana shows four dashboards, "
                   "Alertmanager sends an email when something breaks, with what to check."),
}

# box -> (label, PromQL, format); formats: rate (/s), s, ms, pct, int, mib
NUMBERS = {
    "producer": [("messages per second into Kafka",
                  'sum(delta(kafka_topic_partition_current_offset{topic=~"foot-(tracking|ball|events)"}[30s])) / 30',
                  "rate")],
    "kafka": [("messages per second", 'sum(delta(kafka_topic_partition_current_offset{topic=~"foot-.+"}[30s])) / 30',
               "rate"),
              ("Bronze writer lag (messages)", 'sum(kafka_consumergroup_lag{consumergroup="bronze-writer"})', "int"),
              ("messages kept (7 days)", 'sum(kafka_topic_partition_current_offset{topic=~"foot-.+"}) - '
                                         'sum(kafka_topic_partition_oldest_offset{topic=~"foot-.+"})', "int")],
    "spark": [("last batch", 'max(football_spark_batch_duration_seconds)', "s"),
              ("rows per second processed", 'sum(football_spark_processed_rows_per_second)', "rate"),
              ("messages not processed yet", 'max(football:consumer_lag{source="spark"})', "int")],
    "live": [("delay p95, last 5 min", "football:live_delay_seconds:p95_5m", "s"),
             ("messages not read yet", "sum(football_live_consumer_lag_messages)", "int")],
    "bronze": [("rows written per second",
                'sum(delta(kafka_consumergroup_current_offset{consumergroup="bronze-writer"}[1m])) / 60', "rate"),
               ("MinIO free space", "minio_cluster_capacity_usable_free_bytes", "gib")],
    "silver": [("Silver Soda checks passed",
                'sum(football_soda_checks{layer="silver", result=~"pass|warn"}) / sum(football_soda_checks{layer="silver"})',
                "pct"),
               ("last Silver step", 'football_dagster_step_duration_seconds{dagster_job="match_pipeline", step="silver"}',
                "s")],
    "gold": [("Gold Soda checks passed",
              'sum(football_soda_checks{layer="gold", result=~"pass|warn"}) / sum(football_soda_checks{layer="gold"})',
              "pct"),
             ("slowest Gold after the final whistle", "max(football_gold_freshness_seconds)", "s"),
             ("dbt tests passed", 'sum(football_dbt_tests{status="pass"}) / sum(football_dbt_tests)', "pct")],
    "analysis": [("answering", 'probe_success{service="app"}', "yesno"),
                 ("up over 7 days", "slo:app_up_ratio:7d", "pct")],
    "dagster": [("runs in the last 7 days", "sum(football_dagster_runs)", "int"),
                ("run success (normal runs)", "slo:run_success_ratio:7d", "pct"),
                ("answering", 'probe_success{service="dagster"}', "yesno")],
    "monitoring": [("alerts firing", 'count(ALERTS{alertstate="firing"}) or vector(0)', "int"),
                   ("services answering", 'count(up == 1)', "int"),
                   ("services not answering", 'count(up == 0) or vector(0)', "int")],
    "skillcorner": [],
}


def fmt(value: float | None, kind: str) -> str:
    if value is None or value != value:              # missing or NaN
        return "–"
    return {"rate": lambda v: f"{v:,.0f}/s", "s": lambda v: f"{v:,.1f} s", "ms": lambda v: f"{v:,.0f} ms",
            "pct": lambda v: f"{v:.0%}", "int": lambda v: f"{v:,.0f}", "gib": lambda v: f"{v / 2**30:,.1f} GiB",
            "yesno": lambda v: "yes" if v >= 1 else "no"}[kind](value)
