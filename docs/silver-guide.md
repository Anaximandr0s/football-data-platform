# Start here: Silver and Gold

Ingestion and bronze are finished and verified. This guide is everything you need to build Silver
(Spark + Iceberg), Gold (dbt + DuckDB), the checks (Soda), then Dagster and Streamlit.

## 1. Get the platform running (15 minutes)

Follow the Quick start in the [README](../README.md), until `make check MATCH=m001` and
`make check MATCH=m002` both print OK. Your MinIO is local to your machine: the data you read is
the data you replayed yourself, and the match ids are pinned, so it is identical to ours.

## 2. What is in bronze

`s3://bronze/<table>/match_id=<id>/ingest_date=<day>/part-*.parquet`, one folder per match.

| Table | Grain | m001 rows | m002 rows | Dedup key |
|---|---|---|---|---|
| tracking | player x second | 97,416 | 105,534 | match_id, player_id, ts |
| events | one action | 1,741 | 1,878 | event_id |
| ball | second | 4,428 | 4,797 | match_id, ts |
| players | player | 32 | 32 | match_id, player_id |
| matches | match | 1 | 1 | match_id |

Counts are for ONE replay; each extra replay adds duplicates. After your deduplication you must
get exactly these numbers back. Every column is defined in [`contrat_donnees.md`](contrat_donnees.md).

Reading it (starting point, not tested on a cluster): Spark needs the `hadoop-aws` package and
```
spark.hadoop.fs.s3a.endpoint=http://localhost:9000      # http://minio:9000 from inside Docker
spark.hadoop.fs.s3a.path.style.access=true
spark.hadoop.fs.s3a.access.key=<MINIO_ROOT_USER>        # from .env
spark.hadoop.fs.s3a.secret.key=<MINIO_ROOT_PASSWORD>
```
then `spark.read.parquet("s3a://bronze/tracking/")`. The files contain a `match_id` column AND the
folder is `match_id=...`: if Spark complains, read one match folder at a time
(`s3a://bronze/tracking/match_id=m001/`) and add the column yourself.

## 3. What Silver must do (bronze was kept raw on purpose)

| # | Task | Details |
|---|---|---|
| 1 | Deduplicate | keys in the table above, keep one row per key |
| 2 | Do not trust file order | sort by (player_id, ts); files are micro-batches in arrival order |
| 3 | Add the team | join `players` on (match_id, player_id) to get `team_id` on tracking |
| 4 | Flip directions | where `matches.home_side_pN` is `right_to_left` (period 2 in m001), set x = 105 - x and y = 68 - y for tracking, ball and events (x_start, y_start, x_end, y_end). After that HOME attacks toward x = 105 in both halves. Needed for heatmaps and shot maps |
| 5 | Correct positions | clip x to [0, 105] and y to [0, 68]; set `was_corrected`. Before clipping you must find 735 such rows in m001 and 618 in m002 |
| 6 | Speed | null stays null (never 0). `is_sprint` = speed_kmh > 25 (null means false) |
| 7 | Gaps | about a quarter of the seconds do not exist (see below). Do not invent positions across a gap; adding an `is_after_gap` flag is enough |
| 8 | Write Iceberg | `silver.tracking` (FOO-03: grain player x second), `silver.events`, `silver.ball`, `silver.players`, `silver.matches` |

Suggested `silver.tracking` columns: `match_id, player_id, team_id, period, ts, x, y, speed_kmh,
is_sprint, was_corrected` (+ `is_after_gap` if you want it). The final shape is yours to decide.

## 4. Things that will surprise you

- **Gaps.** Only 73% (m001) and 78% (m002) of the seconds have data; players and ball are missing
  together. They are mostly dead-ball stoppages without a broadcast view of the pitch. Distance and
  sprint totals therefore cover tracked time only: write this in the report.
- **Player ids are per match.** `H01` in m001 and `H01` in m002 are different people. Always group by
  (match_id, player_id).
- **Shots.** `shot` and `goal` are separate types: a shot map is `shot` + `goal`. The source gives no
  saved/blocked/off-target outcome (`outcome` is just `shot`).
- **Score.** `matches` only has the final score. For the live score count `goal` events with
  `ts` up to the current second, per `team_id`. Final check: goals equal 5 in m001 (2-3) and 1 in m002 (0-1).
- **Passes** have a `receiver_id` (null for other types): use it for the pass network.
- **Event types:** pass, shot, goal, tackle, foul, pressure. There is no corner.
- **Names are real** (players, teams, league) and kit colours are in `matches`, so use them in the app.
  Technical keys stay `H01` / `HOME`.

## 5. Checks (Soda, FOO-05)

- Every second that exists has exactly 22 tracking rows per match.
- Positions are inside 105 x 68 in Silver (before correction you will find the rows from step 5).
- `speed_kmh` <= 40 (bronze has none above; null is allowed).
- Event types are in {pass, shot, goal, tackle, foul, pressure}.
- Goals in events = `home_score + away_score` of `matches`.
- Row counts after deduplication equal the table in section 2.

## 6. Gold (FOO-04, FOO-07) and the app

Planned tables (grain in `schema.yml`): `gold_player_match_stats` (distance, sprints, max speed,
actions by type), `gold_team_match_stats`, `gold_zone_occupancy`, `gold_pass_network`
(passer x receiver), `gold_shots`, `gold_player_5min`.
Distance = sum of `speed_kmh / 3.6` over tracked seconds (speed is metres per second x 3.6).

Streamlit pages suggested: live match (22 dots and score), player (heatmap), shots and passes,
teams (HOME vs AWAY, and m001 vs m002 for FOO-09: the same home club plays both matches).

## 7. Streaming and orchestration

- **FOO-08:** read topic `foot-tracking` (JSON, key `player_id`, 3 partitions) from `localhost:29092`
  (`kafka:9092` inside Docker). Messages carry `ts` but no timestamp: build `event_time = kick-off + ts seconds`
  yourself, then use 5-minute windows.
- **Dagster:** a match is over when the largest `ts` in bronze reaches `matches.p2_end_ts`; trigger Gold
  and the post-match report from that.

## 8. Rules

Change a table or column only through a pull request that updates both `ingestion/schemas.py` and
[`contrat_donnees.md`](contrat_donnees.md) and names the person to warn. Ask the ingestion owner if a
bronze column is missing: adding one is cheap now and expensive later.