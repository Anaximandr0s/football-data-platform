"""progress.py: the last progress of each streaming query, written to a JSON file the pipeline exporter reads.

Spark Structured Streaming keeps its Kafka offsets in its checkpoint, not in a Kafka consumer group, so a Kafka exporter
cannot see how far behind it is. Spark knows it: each batch reports how many offsets it is behind the latest ones."""
import json
import os
import time
from pathlib import Path

from pyspark.sql.streaming import StreamingQueryListener

PROGRESS_FILE = Path(os.getenv("STREAMING_PROGRESS_FILE", "data/streaming/progress.json"))


def summary(progress: dict) -> dict:
    """The few numbers worth watching in one StreamingQueryProgress (its JSON form)."""
    behind = [float(s["metrics"]["maxOffsetsBehindLatest"]) for s in progress.get("sources", [])
              if "maxOffsetsBehindLatest" in (s.get("metrics") or {})]
    return {"batch_id": progress["batchId"],
            "input_rows": progress.get("numInputRows", 0),
            "input_rows_per_second": progress.get("inputRowsPerSecond") or 0.0,
            "processed_rows_per_second": progress.get("processedRowsPerSecond") or 0.0,
            "batch_duration_ms": (progress.get("durationMs") or {}).get("triggerExecution", 0),
            "offsets_behind_latest": sum(behind) if behind else None}


class ProgressFile(StreamingQueryListener):
    """Keeps data/streaming/progress.json up to date: one entry per query, with the time Spark last reported."""

    def __init__(self, path: Path = PROGRESS_FILE):
        self.path = path
        self.queries: dict[str, dict] = {}

    def onQueryStarted(self, event) -> None:  # noqa: N802 - the names Spark calls
        self.queries[event.name] = {"id": str(event.id), "reported_at": time.time(), "running": True}
        self._write()

    def onQueryProgress(self, event) -> None:  # noqa: N802
        progress = json.loads(event.progress.json)
        self.queries[progress["name"]] = {**summary(progress), "id": progress["id"], "reported_at": time.time(),
                                          "running": True}
        self._write()

    def onQueryIdle(self, event) -> None:  # noqa: N802 - no new data: still alive, nothing behind
        for q in self._of(event.id):
            q.update(reported_at=time.time(), input_rows_per_second=0.0, processed_rows_per_second=0.0)
        self._write()

    def onQueryTerminated(self, event) -> None:  # noqa: N802
        for q in self._of(event.id):
            q["running"] = False
        self._write()

    def _of(self, query_id) -> list[dict]:
        return [q for q in self.queries.values() if q.get("id") == str(query_id)]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.queries, indent=1), encoding="utf-8")
        tmp.replace(self.path)          # the exporter never reads a half-written file
