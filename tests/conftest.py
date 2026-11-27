"""Fixtures shared by several test folders: the tiny hand-made match, raw then prepared."""

import json
import sys

import pytest

from ingestion import ingest_foot
from tests.ingestion.tiny_match import _events, _frames, match_info

SC_ID = 42


def run(module, monkeypatch, *args: str) -> None:
    """Run a command-line module's main() with these arguments."""
    monkeypatch.setattr(sys, "argv", [module.__name__, *args])
    module.main()


@pytest.fixture
def info():
    return match_info()


@pytest.fixture
def raw_dir(tmp_path, info):
    src = tmp_path / "raw" / str(SC_ID)
    src.mkdir(parents=True)
    (src / f"{SC_ID}_match.json").write_text(json.dumps(info), encoding="utf-8")
    (src / f"{SC_ID}_tracking_extrapolated.jsonl").write_text("\n".join(_frames()), encoding="utf-8")
    _events().to_csv(src / f"{SC_ID}_dynamic_events.csv", index=False)
    return tmp_path / "raw"


@pytest.fixture
def prepared(tmp_path, raw_dir, monkeypatch):
    out = tmp_path / "prepared"
    run(ingest_foot, monkeypatch, "--match", "t1", "--sc-id", str(SC_ID), "--raw-dir", str(raw_dir), "--out", str(out))
    return out
