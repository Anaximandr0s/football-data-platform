# Architecture

## Two paths

- **Batch** (analysis after the match): Kafka -> bronze -> silver -> gold, orchestrated by Dagster.
- **Stream** (live display): Kafka -> Spark Structured Streaming (5- and 15-minute windows) -> Kafka `foot-live-stats` -> Streamlit, and Kafka -> Streamlit for the positions and the score.

## Layers

| Layer | Where | Tool | Content |
|---|---|---|---|
| Source | `data/raw`, `data/prepared` | Python (`ingestion/`) | SkillCorner files converted into 5 Parquet tables |
| Ingestion | Kafka topics `foot-tracking`, `foot-events`, `foot-ball`, `foot-players`, `foot-matches` | Kafka (KRaft, 1 broker) | the match replayed at x1..x60 |
| Bronze | MinIO bucket `bronze` | `ingestion/bronze_writer.py` | raw rows + Kafka metadata, partitioned by match |
| Silver | MinIO bucket `silver` | Spark (standalone cluster in `docker-compose.yml`: `spark-master`, `spark-worker`) + Iceberg | cleaned, deduplicated, player x second |
| Gold | MinIO bucket `gold` | dbt + DuckDB, Soda checks | statistics per player and team, zones, passes, shots |
| Orchestration | `dagster/` | Dagster (webserver + daemon) | the chain of a match when its replay ends |
| Presentation | `app/streamlit` | Streamlit + mplsoccer | live pitch, heatmaps, shot and pass maps |

## Topics

| Topic | Key | Partitions |
|---|---|---|
| foot-tracking | player_id | 3 (order kept per player) |
| foot-events, foot-ball, foot-players, foot-matches | match_id or player_id | 1 |
| foot-live-stats (compacted) | replay_id, match_id, window, team or player | 1 |

Every replay message carries the header `replay_id` (`m001-20261116T101503Z`): two replays of a match never mix.

## Bronze layout

`s3://bronze/<table>/match_id=<id>/ingest_date=<day>/part-<epoch_ms>-<n>.parquet`. Partitioned by match, as the brief asks.
The writer is the always-on service `bronze-writer` (`make up`, restarted if it stops). It buffers per (table, match) and writes a file every 10 s or 5,000 rows, so two matches replayed at the same time never mix.
`ingest_date` (UTC day of writing) is the time partition. Delivery is at-least-once; Silver deduplicates.

## Silver layout

Iceberg tables `lake.silver.tracking | events | ball | players | matches` (catalog `lake`, Hadoop catalog, warehouse
`s3://silver/warehouse`), partitioned by `match_id`. Built per match by `spark/silver/bronze_to_silver.py`:
deduplicated on the bronze keys, sorted by (player_id, ts), `team_id` added to tracking, attack direction normalised
(HOME attacks toward x = 105), tracking positions clipped to 105 x 68 with `was_corrected`, `is_sprint` (> 25 km/h)
and `is_after_gap` flags. Gaps are never filled. A run replaces the partition of the match it processes (idempotent), and
nothing is written if the counts or goals do not match the ingestion manifest. Run with `make silver MATCH=m001` (a one-shot `silver` container submits to `spark://spark-master:7077`). Details, columns and decisions:
[`spark/silver/README.md`](../spark/silver/README.md).

## Streaming (FOO-08)

`spark/streaming/live_stats.py`, started by `make streaming` (container `streaming-5min`, one core of `spark-worker`, Spark UI
on http://localhost:4040; `make streaming-stop`). It must run **before** a replay starts: it reads only new messages.
Three queries read `foot-tracking`, `foot-ball` and `foot-events`, join the replay's `foot-matches` and `foot-players`
messages (read as tables at each micro-batch), and group by replay and football window (`clock.window_index`, the rule of
`int_football_windows`), not by Spark's time windows. `players-5min` gives F4 and F5, `teams-5min` gives F2, and
`pressing-15min` gives C3, with the formulas of Gold. Every 5 s a micro-batch sends the windows that changed to the
compacted topic `foot-live-stats`, as full values (`spark/streaming/rows.py`); the Live page reads them.

- **Checkpoint** `s3a://checkpoints/streaming-5min/<query>` (MinIO): Kafka offsets and aggregation state. A restart goes on
  where it stopped; a micro-batch played twice sends the same full rows again, which overwrite.
- **Duplicates**: a repeated message counts once (dropDuplicatesWithinWatermark, 10 minutes of Kafka time). Known
  limit: a duplicate arriving more than 10 minutes after the first copy is counted twice in the live stats (Gold is not
  affected: Silver deduplicates the whole match).
- **Complete**: a window is final once tracking has reached its end + 10 s of match time, or the last second of the match.

Proof (2026-11-16): after a full replay of m001 at x10, stopped at minute 40 and restarted, and after an earlier one at
x60, all 506 rows of each replay are complete and equal Gold value by value (`gold_match_timeline` 40 windows,
`gold_player_5min` 450, `gold_pressing` 16); the only differences are 0.1 m distance ties on an exact .x5 sum (9 and 4
rows), which Spark and DuckDB round apart. m003 at x60 (the match with 4 speeds above 40 km/h): 502 rows, all complete
and equal Gold (40 + 446 + 16 windows; 12 distance ties on an exact .x5 sum). [Spark UI](img/spark_ui_streaming.png),
[Live panel](img/live_5min_panel_m001.png).

## Orchestration (Dagster)

`make dagster` starts the webserver (http://localhost:3000) and the daemon; one image (`dagster/Dockerfile`) runs both and
every run. When a replay's tracking reaches the last second of its match (`p2_end_ts` of its own `foot-matches` message,
matched by `replay_id`), the sensor `replay_end` starts `match_pipeline` for that match:

`bronze` (the writer has no lag, then `check_bronze`) -> `silver` (Spark job, driver in the daemon container) ->
`soda_silver` (blocking check) -> dbt models (`dagster-dbt`, one `dbt build`) -> `soda_gold` (blocking, one result per Gold
table) -> `match_report`.

- **Partitions**: every asset by `match_id`. Gold holds every match in one DuckDB file, so it is rebuilt whole; its
  partition says which match triggered it.
- **One Gold build at a time**: the steps that open the DuckDB file share the pool `duckdb` (limit 1).
- **Retries**: Silver and dbt, 2 retries 30 s apart. **Schedule**: Soda Silver + Gold at 03:00 UTC.
- **Spark from a container**: the driver runs in `dagster-daemon` (`spark.driver.host=dagster-daemon`), the executors on
  the worker; one core per Silver run (`spark.cores.max=1`), so the streaming job keeps its core.
- After each run, `data/pipeline/runs.json` and `graph.json` feed the Pipeline & lineage page.

Guide and limits: [`dagster/README.md`](../dagster/README.md).

## Design principles

- **Bronze is raw**: ingestion changes the shape, never the values; Silver cleans ([ADR 0003](adr/0003-real-data-skillcorner.md)).
- **One contract**: `ingestion/schemas.py` (`SCHEMAS`) and [`contrat_donnees.md`](contrat_donnees.md) describe the same tables.
- **Idempotent and checkable**: every stage prints counts; `make check` compares bronze with the source.
- **Simple stack**: single-broker Kafka and single-node MinIO; sizes are set in `docker-compose.yml`.

## Gold tables

dbt-core + dbt-duckdb (`dbt/`), run by `make gold` in the `dbt` container: five staging tables (a copy of Silver, read with
`iceberg_scan`) and 16 Gold tables, tested against Silver, kept in the DuckDB file `data/football.duckdb` and exported as
Parquet to `s3://gold/<table>.parquet`. DuckDB is embedded (no server); `make gold-sql` queries the file read-only.
Specification: [`gold-guide.md`](gold-guide.md). Guide of the code: [`dbt/README.md`](../dbt/README.md).

`gold_player_match_stats` (player x match) · `gold_team_match_stats` (team x match) · `gold_zone_occupancy` (player x zone) ·
`gold_pass_network` (passer x receiver x match) · `gold_shots` (one shot) · `gold_player_5min` (player x 5-minute window),
and the nine MatchLens tables of [`product.md`](product.md) section 7 (timeline, player card, team shape, pressing,
build-up, fatigue, space control, team profile, events).

## Quality (Soda)

Soda Core 3.5 runs SodaCL checks on Silver (`soda/checks/silver.yml`, 73 checks) and on the Gold file (`soda/checks/gold.yml`,
130 checks) through one DuckDB connection built by `soda/run_checks.py`; nothing is written to the data. The exit code (0 / 1) is
what Dagster will use to block the next step; each run also writes `data/soda/<layer>.json` for the dashboard. `make soda-demo`
damages a copy on purpose to show the checks catch it. Soda has its own image because its DuckDB connector pins DuckDB 1.0
(see [`soda/README.md`](../soda/README.md)). The columns and types the schema checks enforce are in
[`contrat_donnees.md`](contrat_donnees.md), sections 9 and 10.

## Dashboard (Streamlit)

`app/streamlit/` (`make app`, http://localhost:8501): the MatchLens site of [`product.md`](product.md) section 8. Home (match
and view), LIVE, MATCHES (library, replay, compare), FAN VIEW or COACH VIEW, BEHIND THE DATA; a router (`app.py`) keeps the
chosen view and match from page to page. It reads the Gold file and the Soda results **read-only** (the
repository is mounted `:ro`, the DuckDB file is opened for one query at a time so it never blocks a `make gold`). The Live
match page (FOO-06) reads Kafka instead: one background consumer in the `app` container keeps the state of each replayed
match, and the page redraws it about once per second. See [`app/streamlit/README.md`](../app/streamlit/README.md).
