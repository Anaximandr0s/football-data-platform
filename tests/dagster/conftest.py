"""The Dagster code location loads from a dbt manifest: one is parsed into a temporary folder (no database needed).
Skipped when Dagster or dbt is not installed."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dagster"))


@pytest.fixture(scope="session")
def defs(tmp_path_factory):
    pytest.importorskip("dagster")
    pytest.importorskip("dagster_dbt")
    if shutil.which("dbt") is None:
        pytest.skip("dbt is not installed")
    target = tmp_path_factory.mktemp("dbt_target")
    proc = subprocess.run(["dbt", "parse", "--project-dir", str(ROOT / "dbt"), "--profiles-dir", str(ROOT / "dbt"),
                           "--target-path", str(target), "--log-path", str(target)], capture_output=True, text=True,
                          env={**os.environ, "DBT_TARGET": "dev", "GOLD_DUCKDB_PATH": str(target / "gold.duckdb")})
    assert proc.returncode == 0, proc.stdout[-2000:]
    os.environ["DBT_MANIFEST"] = str(target / "manifest.json")
    from football_platform.definitions import defs as definitions

    return definitions
