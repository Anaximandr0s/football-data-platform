"""Fixtures of the dashboard tests: a real Gold DuckDB file built by dbt from the tiny Silver of tests/dbt, so the
dashboard is tested against the genuine Gold tables. Skipped when dbt is not installed."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app" / "streamlit"
sys.path.insert(0, str(APP_DIR))   # the pages do `import data, viz` like `streamlit run app/streamlit/app.py` does
os.environ.setdefault("MPLBACKEND", "Agg")


def _load_gold_fixture():
    spec = importlib.util.spec_from_file_location("gold_fixture", ROOT / "tests" / "dbt" / "test_gold_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def gold_env(tmp_path_factory):
    """Environment variables pointing the app to a built Gold file and a Soda result folder."""
    fixture = _load_gold_fixture()
    if fixture.DBT is None:
        pytest.skip("dbt is not installed")
    tmp = tmp_path_factory.mktemp("app_gold")
    silver = tmp / "silver"
    fixture._write_silver(silver)
    run = fixture._dbt(tmp, silver, "build")
    assert run.returncode == 0, run.stdout[-3000:]
    soda = tmp / "soda"
    soda.mkdir()
    (soda / "silver.json").write_text(json.dumps({
        "layer": "silver", "finished_at_utc": "2026-11-08T10:00:00Z", "passed": 2, "failed": 1, "warned": 0, "errors": 0,
        "checks": [{"name": "a check that passed", "table": "silver_tracking", "outcome": "pass", "definition": "x"},
                   {"name": "a check that failed", "table": "silver_events", "outcome": "fail", "definition": "y",
                    "detail": "2 failing row(s), first: match_id=m1, team_id=HOME"},
                   {"name": "another one that passed", "table": "silver_ball", "outcome": "pass", "definition": "z"}]}))
    return {"GOLD_DUCKDB_PATH": str(tmp / "gold.duckdb"), "SODA_OUT_DIR": str(soda)}


@pytest.fixture()
def app_env(gold_env, monkeypatch):
    for key, value in gold_env.items():
        monkeypatch.setenv(key, value)
    return gold_env
