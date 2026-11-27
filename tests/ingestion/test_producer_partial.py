"""A replay started after the first second of the match is partial: its id says so, before anything is sent."""

import subprocess
import sys

import pytest

from ingestion import replay_ids
from ingestion.config import PREPARED_DIR, ROOT


def replay_id_of(*args) -> str:
    """The first line the producer prints; it is stopped right after (a dry run still waits in real time)."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "ingestion.producer_foot", "--match", "m001", "--dry-run", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        return next(line.strip().split("=", 1)[1] for line in proc.stdout if line.startswith("replay_id="))
    finally:
        proc.terminate()
        proc.wait(timeout=30)


@pytest.mark.skipif(not (PREPARED_DIR / "m001").exists(), reason="data/prepared/m001 not present (make data)")
def test_a_late_start_is_partial_a_kickoff_start_is_not():
    assert not replay_ids.is_partial(replay_id_of("--speed", "60"))
    assert replay_ids.is_partial(replay_id_of("--speed", "60", "--start", "4000"))
