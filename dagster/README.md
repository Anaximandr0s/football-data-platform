# dagster

Orchestration of the batch path: when a replay ends, the chain of its match runs by itself, and a failed quality check
stops it before bad data reaches Gold or the dashboard.

```bash
make up         # Kafka, MinIO, Spark and the Bronze writer (service bronze-writer)
make dagster    # Dagster on http://localhost:3000 (webserver + daemon)
make replay MATCH=m001 SPEED=60     # ~100 s later the run of m001 starts on its own
```

## How it works

| Asset or check | Runs | Notes |
|---|---|---|
| `bronze` | repeats `python -m ingestion.check_bronze --replay <replay_id>` every 10 s until the replay's folder holds every row of the prepared match (180 s at most) | only this replay counts: replays still streaming do not hold it back (the writer's total lag never reaches 0 while they run) |
| `silver` | `spark-submit spark/silver/bronze_to_silver.py --match <id> --replay <replay_id>` on `spark://spark-master:7077` | driver in the daemon container (`spark.driver.host=dagster-daemon`), executors on the worker, one core per run (the streaming job keeps its two); 2 retries, 30 s apart |
| `soda_silver` (blocking check on `silver`) | `soda/run_checks.py --layer silver` | a failure skips everything after it |
| dbt models, `gold_*` | `dbt build --vars '{export_gold: true}'` (dagster-dbt) | one asset per model, the dbt tests as checks; rebuilds the whole DuckDB file; 2 retries |
| `soda_gold` (blocking check on each `gold_*`) | `soda/run_checks.py --layer gold` | one result per Gold table |
| `match_report` | reads Gold | `data/pipeline/reports/<match_id>.json`: score, coverage, team totals |

Every asset is partitioned by `match_id` (partitions added by the sensor). Gold is rebuilt whole for each match: its
partition only says which match triggered it.

- **Sensor `replay_end`** (every 15 s): reads `foot-matches` and the new `foot-tracking` messages (offsets kept in the
  cursor). A replay whose tracking reaches `p2_end_ts` starts `match_pipeline` for its match; the run key is the
  `replay_id`, so a replay starts one run, never two.
- **Schedule `nightly_quality_schedule`**: 03:00 UTC, the Soda checks of Silver and Gold, nothing rebuilt.
- **Sensors `run_log_success` / `run_log_failure`**: after each run, `data/pipeline/runs.json` and `graph.json`, read by
  the Pipeline & lineage page.
- **One Gold build at a time**: dbt, `soda_gold` and `match_report` open the DuckDB file; they share the pool `duckdb`
  (limit 1, `dagster.yaml`). A second match ending meanwhile waits for the slot instead of colliding on the file.
- **Damaged-data demo**: launch `match_pipeline` from the UI with the config
  `ops: {silver_soda_silver: {config: {inject_damage: true}}}` and the tag `purpose=demo`. The Silver checks run on a
  damaged view (the data is not touched), fail, and Gold is not built. The tag keeps this failure, wanted, out of the
  run-success service level (monitoring); any run started for a test gets a `purpose` tag.

Runs are queued (at most 2 at once) and executed by the daemon. History lives in the volume `dagster-storage`.

## Tests

`python -m pytest tests/dagster` (when a replay is over, what a Soda result means, the order of the graph, the blocking
checks, the pool and the retries). The page that shows the runs: `tests/app/test_behind_the_data.py`.

## Limits

- The code location reads `dbt/target/manifest.json`, written by the one-shot `dagster-init` (`dbt parse`) at
  `make dagster`: after changing a dbt model, run `make dagster` again.
- A replay already over when the sensor first starts is not picked up (the cursor starts at the end of `foot-tracking`).
- SQLite storage: fine for one machine; a shared deployment would use Postgres.
