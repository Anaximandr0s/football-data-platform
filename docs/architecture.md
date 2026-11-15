# Architecture

## Two paths

- **Batch** (analysis after the match): Kafka -> bronze -> silver -> gold, orchestrated by Dagster.
- **Stream** (live display): Kafka -> Spark Structured Streaming (5-minute windows) and Kafka -> Streamlit.

## Layers

| Layer | Where | Tool | Content |
|---|---|---|---|
| Source | `data/raw`, `data/prepared` | Python (`ingestion/`) | SkillCorner files converted into 5 Parquet tables |
| Ingestion | Kafka topics `foot-tracking`, `foot-events`, `foot-ball`, `foot-players`, `foot-matches` | Kafka (KRaft, 1 broker) | the match replayed at x1..x60 |
| Bronze | MinIO bucket `bronze` | `ingestion/bronze_writer.py` | raw rows + Kafka metadata, partitioned by match |
| Silver | MinIO bucket `silver` | Spark (standalone cluster in `docker-compose.yml`: `spark-master`, `spark-worker`) + Iceberg | cleaned, deduplicated, player x second |
| Gold | MinIO bucket `gold` | dbt + DuckDB, Soda checks | statistics per player and team, zones, passes, shots |
| Orchestration | | Dagster | Gold and post-match report when a match ends |
| Presentation | `app/streamlit` | Streamlit + mplsoccer | live pitch, heatmaps, shot and pass maps |

## Topics

| Topic | Key | Partitions |
|---|---|---|
| foot-tracking | player_id | 3 (order kept per player) |
| foot-events, foot-ball, foot-players, foot-matches | match_id or player_id | 1 |

## Bronze layout

`s3://bronze/<table>/match_id=<id>/ingest_date=<day>/part-<epoch_ms>-<n>.parquet`. Partitioned by match, as the brief asks.
The writer buffers per (table, match) and writes a file every 10 s or 5,000 rows, so two matches replayed at the same time never mix.
`ingest_date` (UTC day of writing) is the time partition. Delivery is at-least-once; Silver deduplicates.

## Silver layout

Iceberg tables `lake.silver.tracking | events | ball | players | matches` (catalog `lake`, Hadoop catalog, warehouse
`s3://silver/warehouse`), partitioned by `match_id`. Built per match by `spark/silver/bronze_to_silver.py`:
deduplicated on the bronze keys, sorted by (player_id, ts), `team_id` added to tracking, attack direction normalised
(HOME attacks toward x = 105), tracking positions clipped to 105 x 68 with `was_corrected`, `is_sprint` (> 25 km/h)
and `is_after_gap` flags. Gaps are never filled. A run replaces the partition of the match it processes (idempotent), and
nothing is written if the counts or goals do not match the ingestion manifest. Run with `make silver MATCH=m001` (a one-shot `silver` container submits to `spark://spark-master:7077`). Details, columns and decisions:
[`spark/silver/README.md`](../spark/silver/README.md).

## Design principles

- **Bronze is raw**: ingestion changes the shape, never the values; Silver cleans ([ADR 0003](adr/0003-real-data-skillcorner.md)).
- **One contract**: `ingestion/schemas.py` (`SCHEMAS`) and [`contrat_donnees.md`](contrat_donnees.md) describe the same tables.
- **Idempotent and checkable**: every stage prints counts; `make check` compares bronze with the source.
- **Simple stack**: single-broker Kafka and single-node MinIO; sizes are set in `docker-compose.yml`.

## Gold tables

dbt-core + dbt-duckdb (`dbt/`), run by `make gold` in the `dbt` container: five staging tables (a copy of Silver, read with
`iceberg_scan`) and 15 Gold tables, tested against Silver, kept in the DuckDB file `data/football.duckdb` and exported as
Parquet to `s3://gold/<table>.parquet`. DuckDB is embedded (no server); `make gold-sql` queries the file read-only.
Specification: [`gold-guide.md`](gold-guide.md). Guide of the code: [`dbt/README.md`](../dbt/README.md).

`gold_player_match_stats` (player x match) · `gold_team_match_stats` (team x match) · `gold_zone_occupancy` (player x zone) ·
`gold_pass_network` (passer x receiver x match) · `gold_shots` (one shot) · `gold_player_5min` (player x 5-minute window),
and the nine MatchLens tables of [`product.md`](product.md) section 7 (timeline, player card, team shape, pressing,
build-up, fatigue, space control, team profile, events).

## Quality (Soda)

Soda Core 3.5 runs SodaCL checks on Silver (`soda/checks/silver.yml`, 71 checks) and on the Gold file (`soda/checks/gold.yml`,
121 checks) through one DuckDB connection built by `soda/run_checks.py`; nothing is written to the data. The exit code (0 / 1) is
what Dagster will use to block the next step; each run also writes `data/soda/<layer>.json` for the dashboard. `make soda-demo`
damages a copy on purpose to show the checks catch it. Soda has its own image because its DuckDB connector pins DuckDB 1.0
(see [`soda/README.md`](../soda/README.md)). The columns and types the schema checks enforce are in
[`contrat_donnees.md`](contrat_donnees.md), sections 9 and 10.

## Dashboard (Streamlit)

`app/streamlit/` (`make app`, http://localhost:8501): match overview, players (heatmap, intensity, ranking), shots and passes
(shot map, pass network), compare matches, data quality. It reads the Gold file and the Soda results **read-only** (the
repository is mounted `:ro`, the DuckDB file is opened for one query at a time so it never blocks a `make gold`). The Live
match page (FOO-06) reads Kafka instead: one background consumer in the `app` container keeps the state of each replayed
match, and the page redraws it about once per second. See [`app/streamlit/README.md`](../app/streamlit/README.md).
