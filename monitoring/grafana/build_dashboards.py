"""Writes the 4 Grafana dashboards (monitoring/grafana/dashboards/*.json) from this file.

    python monitoring/grafana/build_dashboards.py

Grafana loads the JSON files at start (provisioning); a test checks they match this script, so a change is made here,
not by clicking in Grafana. Panels are laid out left to right, 24 columns wide."""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}
GREEN, ORANGE, RED, BLUE, GREY = "#2e9e5b", "#d97706", "#c0392b", "#0072B2", "#8a948f"
SERVICE = 'label_replace({expr}, "service", "$1", "name", "football-platform-(.+)-1")'
SPARK = (
    'label_replace({{__name__=~"metrics_streaming_driver_spark_streaming_.+_{metric}_Value"}}, "query", "$1", '
    '"__name__", "metrics_streaming_driver_spark_streaming_(.+)_{metric}_Value")'
)


def below(limit: float) -> list:
    """Green under the limit, red from it."""
    return [{"color": GREEN, "value": None}, {"color": RED, "value": limit}]


def above(limit: float) -> list:
    """Red under the limit, green from it."""
    return [{"color": RED, "value": None}, {"color": GREEN, "value": limit}]


def target(expr: str, legend: str = "", instant: bool = False, ref: str = "A") -> dict:
    t = {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref}
    return {**t, "instant": True, "range": False, "format": "table"} if instant else t


def stat(
    title, expr, unit="none", steps=None, w=4, h=4, description="", no_value="no data yet", mappings=None, decimals=None
):
    return {
        "type": "stat",
        "title": title,
        "description": description,
        "_w": w,
        "_h": h,
        "targets": [target(expr)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "noValue": no_value,
                "decimals": decimals,
                "mappings": (mappings or [])
                + [{"type": "special", "options": {"match": "null+nan", "result": {"text": no_value, "color": GREY}}}],
                "thresholds": {"mode": "absolute", "steps": steps or [{"color": BLUE, "value": None}]},
            },
            "overrides": [],
        },
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "center",
            "textMode": "value",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
    }


def series(title, queries, unit="none", w=12, h=8, description="", stack=False, steps=None, min_=None, max_=None):
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "_w": w,
        "_h": h,
        "targets": [target(e, legend, ref=chr(65 + i)) for i, (e, legend) in enumerate(queries)],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": min_,
                "max": max_,
                "custom": {
                    "lineWidth": 2,
                    "fillOpacity": 10,
                    "showPoints": "never",
                    "stacking": {"mode": "normal" if stack else "none"},
                    "thresholdsStyle": {"mode": "line" if steps else "off"},
                },
                "thresholds": {"mode": "absolute", "steps": steps or [{"color": GREEN, "value": None}]},
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull", "max"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def bars(title, expr, legend, unit="none", w=12, h=8, description="", steps=None, max_=None):
    return {
        "type": "bargauge",
        "title": title,
        "description": description,
        "_w": w,
        "_h": h,
        "targets": [{**target(expr, legend), "instant": True, "range": False}],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "min": 0,
                "max": max_,
                "noValue": "no data yet",
                "thresholds": {"mode": "absolute", "steps": steps or [{"color": BLUE, "value": None}]},
            },
            "overrides": [],
        },
        "options": {
            "orientation": "horizontal",
            "displayMode": "basic",
            "showUnfilled": True,
            "valueMode": "text",
            "reduceOptions": {"calcs": ["lastNotNull"]},
        },
    }


def table(title, expr, columns: dict, w=12, h=8, description="", status_column=None):
    """An instant query shown as a table; `columns` renames the labels kept (in order); a 0/1 value becomes a word."""
    overrides = []
    if status_column:
        overrides.append(
            {
                "matcher": {"id": "byName", "options": status_column},
                "properties": [
                    {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    {
                        "id": "mappings",
                        "value": [
                            {
                                "type": "value",
                                "options": {
                                    "0": {"text": "success", "color": GREEN},
                                    "1": {"text": "failed", "color": RED},
                                },
                            }
                        ],
                    },
                ],
            }
        )
    return {
        "type": "table",
        "title": title,
        "description": description,
        "_w": w,
        "_h": h,
        "targets": [target(expr, instant=True)],
        "transformations": [
            {
                "id": "organize",
                "options": {
                    "indexByName": {k: i for i, k in enumerate(columns)},
                    "renameByName": {k: v for k, v in columns.items()},
                    "excludeByName": {
                        k: True for k in ("Time", "__name__", "instance", "job", "service") if k not in columns
                    },
                },
            },
            {"id": "filterFieldsByName", "options": {"include": {"names": list(columns.values())}}},
        ],
        "fieldConfig": {"defaults": {"noValue": "nothing to show"}, "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm"},
    }


def text(title, markdown, w=24, h=3):
    return {"type": "text", "title": title, "_w": w, "_h": h, "options": {"mode": "markdown", "content": markdown}}


def dashboard(uid: str, title: str, description: str, panels: list, refresh="15s", time_from="now-1h") -> dict:
    x = y = row_h = 0
    out = []
    for i, p in enumerate(panels, start=1):
        w, h = p.pop("_w"), p.pop("_h")
        if x + w > 24:
            x, y, row_h = 0, y + row_h, 0
        out.append({"id": i, "datasource": DS, "gridPos": {"x": x, "y": y, "w": w, "h": h}, **p})
        x, row_h = x + w, max(row_h, h)
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": ["matchlens"],
        "editable": False,
        "schemaVersion": 39,
        "version": 1,
        "refresh": refresh,
        "time": {"from": time_from, "to": "now"},
        "timezone": "browser",
        "graphTooltip": 1,
        "panels": out,
        "annotations": {
            "list": [
                {
                    "name": "Benchmark scenario",
                    "datasource": DS,
                    "enable": True,
                    "iconColor": "purple",
                    "expr": "football_benchmark_scenario == 1",
                    "target": {"expr": "football_benchmark_scenario == 1", "refId": "Anno", "interval": "15s"},
                    "titleFormat": "benchmark: {{scenario}}",
                    "step": "15s",
                    "useValueForTime": False,
                }
            ]
        },
        "links": [{"type": "dashboards", "tags": ["matchlens"], "asDropdown": False, "title": "MatchLens"}],
    }


def infrastructure() -> dict:
    cpu = 'sum by (name) (rate(container_cpu_usage_seconds_total{name=~"football-platform-.+"}[1m]))'
    mem = 'container_memory_working_set_bytes{name=~"football-platform-.+"}'
    limit = 'container_spec_memory_limit_bytes{name=~"football-platform-.+"} > 0'
    return dashboard(
        "infrastructure",
        "MatchLens · Infrastructure",
        "The machine and every container: CPU, memory against its limit, disk, restarts.",
        [
            stat(
                "Host CPU",
                '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[2m]))',
                "percentunit",
                below(0.85),
                description="Alert above 85 % for 5 minutes.",
            ),
            stat(
                "Host memory used",
                "1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes",
                "percentunit",
                below(0.9),
            ),
            stat(
                "Disk free",
                'node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}',
                "percentunit",
                above(0.15),
                description="Alert below 15 %.",
            ),
            stat(
                "Containers running",
                'count(container_last_seen{name=~"football-platform-.+"})',
                steps=[{"color": BLUE, "value": None}],
            ),
            stat(
                "Restarts, last hour",
                'sum(changes(container_start_time_seconds{name=~"football-platform-.+"}[1h]))',
                steps=below(1),
                no_value="0",
            ),
            stat(
                "Services down",
                "count(up == 0) or vector(0)",
                steps=below(1),
                description="Scrape targets that do not answer. The Spark streaming driver is only up during make "
                "streaming.",
            ),
            series(
                "Host CPU and memory",
                [
                    ('1 - avg(rate(node_cpu_seconds_total{mode="idle"}[2m]))', "CPU"),
                    ("1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "memory"),
                ],
                "percentunit",
                min_=0,
                max_=1,
                steps=below(0.85),
            ),
            series("CPU per container (cores)", [(SERVICE.format(expr=cpu), "{{service}}")], "none"),
            series(
                "Memory per container, share of its limit",
                [(SERVICE.format(expr=f"{mem} / ({limit})"), "{{service}}")],
                "percentunit",
                min_=0,
                max_=1,
                steps=below(0.9),
                description="Alert above 90 % for 2 minutes.",
            ),
            bars("Memory per container", f"sort_desc({SERVICE.format(expr=mem)})", "{{service}}", "bytes"),
            series(
                "Disk free",
                [('node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}', "free")],
                "percentunit",
                min_=0,
                max_=1,
                steps=above(0.15),
            ),
            table("Scrape targets", "up", {"service": "service", "Value": "up"}, description="1 = answers Prometheus."),
        ],
    )


def streaming() -> dict:
    return dashboard(
        "streaming",
        "MatchLens · Streaming",
        "A replay seen from Kafka: messages per topic, how far behind each reader is, the Spark "
        "Structured Streaming batches and the live delay of the Live page.",
        [
            stat(
                "Replay running",
                "football:replay_running",
                mappings=[
                    {
                        "type": "value",
                        "options": {
                            "0": {"text": "no replay", "color": GREY},
                            "1": {"text": "replay running", "color": GREEN},
                        },
                    }
                ],
                w=6,
            ),
            stat(
                "Kafka messages per second",
                'sum(delta(kafka_topic_partition_current_offset{topic=~"foot-.+"}[1m])) / 60',
                "short",
                w=6,
                decimals=0,
            ),
            stat(
                "Live delay, p95 (5 min)",
                "football:live_delay_seconds:p95_5m",
                "s",
                below(2),
                w=6,
                description="From the Kafka timestamp to the Live page's consumer. Objective: under 2 s.",
                no_value="no live data",
            ),
            stat(
                "Spark queries reporting",
                "count(time() - football_spark_query_reported_timestamp_seconds < 120)",
                w=6,
                steps=above(3),
                no_value="0",
                description="The 3 queries of make streaming report at least every 10 s while they run.",
            ),
            series(
                "Kafka messages per second, per topic",
                [
                    (
                        'sum by (topic) (delta(kafka_topic_partition_current_offset{topic=~"foot-.+"}[1m])) / 60',
                        "{{topic}}",
                    )
                ],
                "short",
            ),
            series(
                "Messages not read yet, per reader",
                [("football:consumer_lag", "{{consumer}}")],
                "short",
                description="bronze-writer: its Kafka consumer group. spark-*: offsets behind, from the query's "
                "progress. live-page: the app's own consumer. Alert when it grows for 2 minutes during "
                "a replay.",
            ),
            series(
                "Spark rows per second, per query",
                [
                    (SPARK.format(metric="inputRate_total"), "in · {{query}}"),
                    (SPARK.format(metric="processingRate_total"), "processed · {{query}}"),
                ],
                "short",
                description="From Spark's own metrics (driver :4040). Processed above in: the query keeps up.",
            ),
            series(
                "Spark batch duration, per query",
                [(SPARK.format(metric="latency") + " / 1000", "{{query}}")],
                "s",
                description="Time to run one micro-batch. The trigger is every 5 s: above it, batches queue up.",
            ),
            series(
                "Live delay",
                [
                    ("histogram_quantile(0.5, sum by (le) (rate(football_live_delay_seconds_bucket[5m])))", "median"),
                    ("football:live_delay_seconds:p95_5m", "p95"),
                ],
                "s",
                steps=below(2),
                min_=0,
            ),
            series(
                "Spark driver memory",
                [
                    ("metrics_streaming_driver_ExecutorMetrics_JVMHeapMemory_Value", "heap"),
                    ("metrics_streaming_driver_ExecutorMetrics_JVMOffHeapMemory_Value", "off-heap"),
                ],
                "bytes",
            ),
        ],
        refresh="10s",
        time_from="now-30m",
    )


def pipeline() -> dict:
    soda_rate = (
        'sum by (dimension) (football_soda_checks{result=~"pass|warn"}) / sum by (dimension) (football_soda_checks)'
    )
    return dashboard(
        "pipeline",
        "MatchLens · Pipeline & data quality",
        "Dagster runs and steps, the Soda checks per quality dimension, the dbt tests and the "
        "freshness of Gold per match.",
        [
            stat(
                "Dagster",
                "football_dagster_up",
                mappings=[
                    {
                        "type": "value",
                        "options": {
                            "0": {"text": "not answering", "color": RED},
                            "1": {"text": "answering", "color": GREEN},
                        },
                    }
                ],
            ),
            stat("Runs, last 7 days", "sum(football_dagster_runs)", steps=[{"color": BLUE, "value": None}]),
            stat(
                "Failed runs, last 7 days", 'sum(football_dagster_runs{status="FAILURE"}) or vector(0)', steps=below(1)
            ),
            stat("Soda checks passed", "slo:blocking_checks_pass_ratio", "percentunit", above(1), decimals=1),
            stat(
                "dbt tests passed",
                'sum(football_dbt_tests{status="pass"}) / sum(football_dbt_tests)',
                "percentunit",
                above(1),
                decimals=1,
            ),
            stat(
                "Slowest Gold, latest replays",
                "max(football_gold_freshness_seconds)",
                "s",
                below(600),
                description="From the final whistle to Gold ready, the slowest match. Objective: 10 minutes.",
            ),
            table(
                "Latest run of each job and match",
                "football_dagster_latest_run_failed",
                {"dagster_job": "job", "match_id": "match", "run_id": "run", "Value": "result"},
                status_column="result",
            ),
            bars(
                "Soda checks passed, per dimension", soda_rate, "{{dimension}}", "percentunit", max_=1, steps=above(1)
            ),
            bars(
                "Step duration, latest match run",
                'sort_desc(football_dagster_step_duration_seconds{dagster_job="match_pipeline"})',
                "{{step}}",
                "s",
            ),
            bars(
                "Gold ready after the final whistle, per match",
                "football_gold_freshness_seconds",
                "{{match_id}}",
                "s",
                steps=below(600),
                description="Green: within 10 minutes (the Data quality page's rule).",
            ),
            table(
                "Failed Soda checks",
                "football_soda_check_failed",
                {"layer": "layer", "dimension": "dimension", "table": "table", "check": "check"},
            ),
            table("Failed dbt tests", "football_dbt_test_failed", {"test": "test"}),
            series(
                "Runs by status, last 7 days",
                [("sum by (status) (football_dagster_runs)", "{{status}}")],
                w=24,
                h=7,
                min_=0,
            ),
        ],
        refresh="30s",
        time_from="now-24h",
    )


def slo() -> dict:
    goals = [
        (
            "Live delay p95 · goal < 2 s",
            "slo:live_delay_p95_seconds:7d",
            "s",
            below(2),
            "95 % of the live messages reach the Live page in under 2 s, over 7 days.",
        ),
        (
            "Gold freshness · goal < 10 min",
            "slo:gold_freshness_seconds:max",
            "s",
            below(600),
            "The slowest match: from the final whistle of its latest replay to Gold ready.",
        ),
        (
            "Run success · goal ≥ 95 %",
            "slo:run_success_ratio:7d",
            "percentunit",
            above(0.95),
            "Dagster runs that succeeded, over 7 days, without the runs started on purpose for a test (tag purpose: "
            "the damaged-data demo, the benchmark rebuild). The next tile counts every run.",
        ),
        (
            "Blocking checks · goal 100 %",
            "slo:blocking_checks_pass_ratio",
            "percentunit",
            above(1),
            "Soda checks that passed in the last run of each layer. All of them block the pipeline.",
        ),
        (
            "App up · goal ≥ 99 %",
            "slo:app_up_ratio:7d",
            "percentunit",
            above(0.99),
            "Share of the 15-second probes the app answered, over 7 days.",
        ),
    ]
    panels = [
        text(
            "Service level objectives",
            "Five promises the platform makes, measured over the last 7 days (the retention of Prometheus). "
            "**Green**: the promise is kept. **Red**: it is not. The graphs below show how each one moved.",
            h=3,
        )
    ]
    for title, expr, unit, steps, description in goals[:3]:
        panels.append(
            stat(title, expr, unit, steps, w=4, h=6, description=description, decimals=2 if unit == "s" else 1)
        )
    panels.append(
        stat(
            "Run success, all runs",
            "slo:run_success_ratio_raw:7d",
            "percentunit",
            w=4,
            h=6,
            steps=[{"color": GREY, "value": None}],
            decimals=1,
            description="Every run, the ones started on purpose for tests included: for reference.",
        )
    )
    for title, expr, unit, steps, description in goals[3:]:
        panels.append(stat(title, expr, unit, steps, w=4, h=6, description=description, decimals=1))
    for title, expr, unit, steps, _ in goals:
        extra = [("slo:run_success_ratio_raw:7d", "all runs")] if expr == "slo:run_success_ratio:7d" else []
        panels.append(
            series(
                title.split(" · ")[0],
                [(expr, "measured"), *extra],
                unit,
                w=8,
                h=7,
                steps=steps,
                min_=0,
                max_=1 if unit == "percentunit" else None,
            )
        )
    return dashboard(
        "slo",
        "MatchLens · Service levels",
        "Five objectives with green or red status.",
        panels,
        refresh="1m",
        time_from="now-7d",
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for build in (infrastructure, streaming, pipeline, slo):
        board = build()
        (OUT / f"{board['uid']}.json").write_text(
            json.dumps(board, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{board['uid']}.json: {len(board['panels'])} panels")


if __name__ == "__main__":
    main()
