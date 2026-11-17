"""Behind the data: the asset graph coloured by a run, the run table, the dbt lineage of a Gold table, and the two pages
run headless (Pipeline & lineage on files like those Dagster writes, Sources & limits on the tiny Gold file)."""
import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import lineage  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit"
GRAPH = {"assets": [{"key": "bronze", "deps": [], "checks": []},
                    {"key": "silver", "deps": ["bronze"], "checks": ["soda_silver"]},
                    {"key": "stg_tracking", "deps": ["silver"], "checks": ["not_null_x"]},
                    {"key": "gold_shots", "deps": ["stg_tracking"], "checks": ["soda_gold"]},
                    {"key": "match_report", "deps": ["gold_shots"], "checks": []}]}
BLOCKED = {"run_id": "r2", "job": "match_pipeline", "status": "FAILURE", "match_id": "m001", "replay_id": None,
           "trigger": "manual", "started": 1_794_800_000, "ended": 1_794_800_120,
           "steps": [{"step": "bronze", "status": "SUCCESS"}, {"step": "silver", "status": "SUCCESS"},
                     {"step": "silver_soda_silver", "status": "FAILURE"}, {"step": "gold", "status": "SKIPPED"},
                     {"step": "soda_gold", "status": "SKIPPED"}, {"step": "match_report", "status": "SKIPPED"}],
           "checks": [{"asset": "silver", "check": "soda_silver", "passed": False}]}
GREEN = {**BLOCKED, "run_id": "r1", "status": "SUCCESS", "trigger": "sensor", "replay_id": "m001-20261116T141951Z",
         "steps": [{"step": s["step"], "status": "SUCCESS"} for s in BLOCKED["steps"]],
         "checks": [{"asset": "silver", "check": "soda_silver", "passed": True}]}


def test_a_failed_soda_check_marks_its_asset_and_blocks_what_follows():
    states = lineage.node_states(GRAPH, BLOCKED)
    assert states == {"bronze": "done", "silver": "failed", "stg_tracking": "blocked", "gold_shots": "blocked",
                      "match_report": "blocked"}
    assert set(lineage.node_states(GRAPH, GREEN).values()) == {"done"}
    dot = lineage.pipeline_dot(GRAPH, BLOCKED)
    assert '"bronze" -> "silver"' in dot and "soda_silver" in dot and lineage.STATE_COLOR["failed"] in dot


def test_the_run_table_says_what_failed_and_what_was_not_built():
    table = lineage.runs_table([BLOCKED, GREEN])
    blocked = table.iloc[0]
    assert blocked.result == "failed" and blocked["what failed"] == "soda_silver on silver, silver_soda_silver"
    assert blocked["not built"] == "gold, soda_gold, match_report" and blocked.minutes == 2.0
    assert table.iloc[1].result == "success" and table.iloc[1].trigger == "sensor"


def test_the_dbt_lineage_goes_back_to_silver():
    manifest = {"nodes": {
        "model.f.gold_shots": {"name": "gold_shots", "resource_type": "model",
                               "depends_on": {"nodes": ["model.f.int_events", "model.f.stg_players"]}},
        "model.f.int_events": {"name": "int_events", "resource_type": "model",
                               "depends_on": {"nodes": ["model.f.stg_events"]}},
        "model.f.stg_events": {"name": "stg_events", "resource_type": "model", "depends_on": {"nodes": []}},
        "model.f.stg_players": {"name": "stg_players", "resource_type": "model", "depends_on": {"nodes": []}},
        "model.f.gold_other": {"name": "gold_other", "resource_type": "model", "depends_on": {"nodes": []}}}}
    names, edges = lineage.ancestors(manifest, "gold_shots")
    assert names == ["gold_shots", "int_events", "stg_events", "stg_players"]
    assert ("int_events", "gold_shots") in edges and ("stg_events", "int_events") in edges
    assert '"silver (Iceberg)" -> "stg_events"' in lineage.dbt_dot(manifest, "gold_shots")


def test_pipeline_page_draws_the_graph_the_runs_and_a_gold_lineage(app_env, monkeypatch, tmp_path):
    out = tmp_path / "pipeline"
    out.mkdir()
    (out / "graph.json").write_text(json.dumps(GRAPH))
    (out / "runs.json").write_text(json.dumps([BLOCKED, GREEN]))
    monkeypatch.setenv("PIPELINE_OUT_DIR", str(out))
    monkeypatch.setenv("DBT_MANIFEST", str(Path(app_env["GOLD_DUCKDB_PATH"]).parent / "target" / "manifest.json"))
    at = AppTest.from_file(str(APP / "sections/pipeline_lineage.py"), default_timeout=90).run()
    assert not at.exception
    assert [s.value for s in at.subheader] == ["Where a Gold table comes from"]      # the simple graph first
    at.toggle[0].set_value(True).run()                                              # "Show details"
    assert [s.value for s in at.subheader] == ["The asset graph", "Latest runs", "Where a Gold table comes from"]
    assert list(at.dataframe[0].value["result"]) == ["failed", "success"]
    assert at.selectbox[1].value == "gold_player_match_stats"
    meanings = at.dataframe[1].value
    assert len(meanings) > 10 and "–" not in set(meanings.meaning)                  # every column explained


def test_pipeline_page_before_any_run_says_what_to_start(app_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_OUT_DIR", str(tmp_path))
    monkeypatch.setenv("DBT_MANIFEST", str(tmp_path / "none.json"))
    at = AppTest.from_file(str(APP / "sections/pipeline_lineage.py"), default_timeout=90).run()
    assert not at.exception and "make gold" in at.info[0].value
    at.toggle[0].set_value(True).run()
    assert "make dagster" in at.info[0].value and "make gold" in at.info[1].value


def test_sources_page_shows_the_source_the_limits_and_the_external_checks(app_env):
    at = AppTest.from_file(str(APP / "sections/sources_limits.py"), default_timeout=90).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "MIT licence" in text and "The camera does not see everything" in text
    words = text.lower()
    assert "bronze" not in words and "normalis" not in words and " ts " not in words      # no technical words
    assert any("FBref match report" in c.value for c in at.caption)          # the sources of docs/external_checks.yml
    assert at.metric[0].value == "SkillCorner"


def test_the_overview_shows_the_batch_and_the_live_paths():
    dot = lineage.overview_dot()
    for edge in ("kafka -> bronze", "bronze -> silver", "silver -> gold", "gold -> report", "kafka -> stream",
                 "stream -> stats", "stats -> live"):
        assert edge in dot


def test_column_meanings_come_from_the_contract_then_the_shared_words():
    contract = ("**gold_x** (S1): one row.\n\n| Column | Type | Meaning |\n|---|---|---|\n"
                "| match_id, team_id | VARCHAR | |\n| a, b | DOUBLE | the a and b share |\n\n**gold_y**: other\n")
    m = lineage.contract_meanings(contract, "gold_x")
    assert m["a"] == m["b"] == "the a and b share" and m["team_id"] == "HOME or AWAY"       # empty -> shared word
    assert lineage.contract_meanings(contract, "gold_z") == {}
