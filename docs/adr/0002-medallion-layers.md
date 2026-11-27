# ADR 0002: Bronze, Silver, Gold

- **Status:** accepted, 2026-10-27; Bronze layout changed 2026-11-17 (one folder per replay)
- **Context:** the same match must serve a live page (seconds after a move) and full statistics after the final
  whistle, and a wrong number must be traceable to the step that made it.
- **Options:**
  1. One database fed directly by Kafka: simple, but raw and cleaned data mix, and a bug in the cleaning loses the raw.
  2. Three layers, each with one job: raw, cleaned, business tables.
- **Decision:** three layers.
  - **Bronze**, MinIO, Parquet: every message as received, never changed. One folder per replay:
    `s3://bronze/<table>/match_id=<id>/replay_id=<replay_id>/ingest_date=<day>/`, so a match replayed twice is two
    separate folders and Silver reads exactly one ([ADR 0005](0005-replay-id-complete-partial.md)).
  - **Silver**, Spark and Iceberg: deduplicated, team added, directions and out-of-pitch positions fixed, `MERGE INTO`
    so a second run changes nothing.
  - **Gold**, dbt and DuckDB: one table per question of the app, with its grain written in the model.
  - Soda checks Silver and Gold; Dagster runs the chain at the final whistle of a whole replay.
- **Consequences:** Bronze grows with every replay (`make bronze-prune KEEP=3` keeps the last three complete replays
  per match). DuckDB reads the Iceberg tables with `iceberg_scan` (the risk named in the first version of this ADR);
  `macros/silver_table.sql` can switch to a Parquet copy of Silver if that ever breaks.
