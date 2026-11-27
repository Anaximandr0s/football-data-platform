"""The monitoring files: every alert can be read by a person, every link leads somewhere, nothing drifts."""

import importlib.util
import json
import re
from pathlib import Path

import yaml

MON = Path(__file__).resolve().parents[2] / "monitoring"
ALERTS = [
    r for g in yaml.safe_load((MON / "prometheus" / "rules" / "alerts.yml").read_text())["groups"] for r in g["rules"]
]


def build():
    spec = importlib.util.spec_from_file_location("build_dashboards", MON / "grafana" / "build_dashboards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_alert_says_what_happened_where_and_what_to_check():
    for rule in ALERTS:
        assert {"title", "summary", "description", "check", "dashboard"} <= set(rule["annotations"]), rule["alert"]
        assert rule["labels"]["severity"] in {"critical", "warning"}, rule["alert"]
        assert rule["labels"]["area"] in {"infrastructure", "streaming", "pipeline", "quality"}, rule["alert"]


def test_every_alert_points_to_a_dashboard_that_exists():
    uids = {json.loads(p.read_text())["uid"] for p in (MON / "grafana" / "dashboards").glob("*.json")}
    assert uids == {"infrastructure", "streaming", "pipeline", "slo"}
    assert {r["annotations"]["dashboard"] for r in ALERTS} <= uids


def test_the_dashboards_in_git_are_the_ones_the_script_builds():
    b = build()
    for make in (b.infrastructure, b.streaming, b.pipeline, b.slo):
        board = make()
        committed = json.loads((MON / "grafana" / "dashboards" / f"{board['uid']}.json").read_text(encoding="utf-8"))
        assert committed == json.loads(json.dumps(board)), "run python monitoring/grafana/build_dashboards.py"


def test_every_placeholder_of_the_alertmanager_files_is_filled_at_start():
    filled = set(re.findall(r"s\|(__[A-Z_]+__)\|", (MON / "alertmanager" / "entrypoint.sh").read_text()))
    for name in ("alertmanager.yml.tmpl", "email.tmpl"):
        used = set(re.findall(r"__[A-Z_]+__", (MON / "alertmanager" / name).read_text()))
        assert used <= filled, (name, used - filled)


def test_lag_and_streaming_alerts_are_muted_while_kafka_is_down():
    config = yaml.safe_load((MON / "alertmanager" / "alertmanager.yml.tmpl").read_text())
    rule = config["inhibit_rules"][0]
    assert rule["source_matchers"] == ['alertname="KafkaDown"'] and rule["target_matchers"] == ['area="streaming"']
    assert {r["alert"] for r in ALERTS if r["labels"]["area"] == "streaming"} == {
        "ConsumerLagGrowing",
        "SparkStreamingStalled",
    }
    assert config["receivers"][0]["email_configs"][0]["send_resolved"] is True
