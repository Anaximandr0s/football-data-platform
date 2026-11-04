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
| Silver | MinIO bucket `silver` | Spark + Iceberg | cleaned, deduplicated, player x second |
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

## Design principles

- **Bronze is raw**: ingestion changes the shape, never the values; Silver cleans ([ADR 0003](adr/0003-real-data-skillcorner.md)).
- **One contract**: `ingestion/schemas.py` (`SCHEMAS`) and [`contrat_donnees.md`](contrat_donnees.md) describe the same tables.
- **Idempotent and checkable**: every stage prints counts; `make check` compares bronze with the source.
- **Simple stack**: single-broker Kafka and single-node MinIO; sizes are set in `docker-compose.yml`.

## Planned Gold tables

`gold_player_match_stats` (player x match) · `gold_team_match_stats` (team x match) · `gold_zone_occupancy` (player x zone) ·
`gold_pass_network` (passer x receiver x match) · `gold_shots` (one shot) · `gold_player_5min` (player x 5-minute window).