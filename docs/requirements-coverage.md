# Requirements coverage

| Ref | Requirement | Type | Owner | Status | Proof |
|---|---|---|---|---|---|
| FOO-01 | A full match: 22 players, 1 position per second, at least 1,000 actions | OBL | ingestion | done (real data instead of generated: confirm with the professor) | `make data`: m001 22 players per second, 1,741 events; m002 1,878 events |
| FOO-02 | Live replay through Kafka at x1 to x60 | OBL | ingestion | done at x60 (x1 to x60 supported) | `make replay`: 100 s for m001, `make counts` |
| FOO-03 | Silver Iceberg table, grain player x second | OBL | Silver / Gold | in progress: code and 13 unit tests done; Iceberg write not yet run on MinIO | `python -m pytest tests/spark`; `make silver MATCH=m001 ARGS=--dry-run` report (counts equal `silver-guide.md`); then add the real `make silver` run |
| FOO-04 | Gold per player: distance, sprints, max speed, actions by type | OBL | Silver / Gold | done: `gold_player_match_stats` and 14 other Gold tables (the 9 MatchLens tables of `product.md` section 7 included), 16 pytest; run on MinIO for m001 and m002 | `make gold` on 2026-11-15: PASS=84 ERROR=0 (dbt models and tests); 27 numbers of the new tables recomputed in pandas from the Silver Parquet, all equal; the 6 first tables identical before and after the new ones (row-by-row diff = 0); `python -m pytest tests/dbt` |
| FOO-05 | Checks: inside the pitch, speed <= 40, 22 players per second | OBL | Silver / Gold | done: page Data quality in six dimensions (every check mapped in `soda/dimensions.yml`, tested; [screenshot](img/data_quality_dimensions.png)); 73 Silver + 136 Gold Soda checks, failure demo, 15 tests; run on MinIO for m001 and m002 | `make soda` on 2026-11-16 (4 matches): silver 73 passed, gold 130 passed, 0 failed; `python -m pytest tests/soda` in the Soda environment; `make soda-demo`: 6 Silver checks and 1 Gold check fail on the injected damage, exit 0 |
| FOO-06 | Streamlit pitch with live positions and score | OBL | both | done: page Live match (pitch, score from goal events, clock, possession, last event, team shape of the current second, camera-gap message); 8 state tests + 3 headless page tests | `make app`, then `make replay MATCH=m001 SPEED=5` while the page is open: on 2026-11-15 it showed 1-0 after the first goal, 2-3 after the fifth ([screenshot](img/live_match_m001_goal5.png)), "No tracking: camera off the pitch" inside the 143 s gap, and 2-3 at full time; `python -m pytest tests/app` |
| FOO-07 | Streamlit heatmap of a player and shot maps | OBL | both | done: Player page (heatmap, shots and passes on the pitch component), Team analysis (shot map, pass network), Live heatmap so far; headless tests; seen in a browser on 2026-11-15 ([Player page](img/player_fan_m001.png), [coach mode](img/player_coach_m001.png), [Live](img/live_player_selected_m001.png)) | `make app`, Player page and Live match with a player clicked; `python -m pytest tests/app` |
| FOO-08 | 5-minute rolling stats with Spark Structured Streaming | OPT | Silver / Gold | done: `spark/streaming/` on the Spark cluster (3 queries, checkpoint on MinIO) writes the 5-min (F2, F4, F5) and 15-min (C3) windows of each replay to the compacted topic `foot-live-stats`; the Live page shows them as complete or in progress; 4 unit tests of the formulas and the completion rule | `make streaming`, then `make replay MATCH=m001 SPEED=10`; on 2026-11-16 the 506 rows of the replay (job stopped at minute 40 and restarted) and of an earlier x60 replay were complete and equal Gold value by value, and so were the 502 rows of m003 at x60; the demo run (m001 at x1 from 04:56, 10 minutes) shows 0-5' and 5-10' complete and 10-15' in progress ([screenshot](img/live_5min_panel_m001_x1.png)) (only 0.1 m .x5 rounding ties, unrounded sums checked equal) ([Spark UI](img/spark_ui_streaming.png), [Live](img/live_5min_panel_m001.png)); `python -m pytest tests/spark tests/app` |
| FOO-09 | Compare two matches, or cluster player profiles | OPT | Silver / Gold | done for comparing (clustering not done): Compare matches shows one team in any of its stored matches, venue and opponent named, with sentences checked against Gold | `make app`, Compare matches: Brisbane Roar at home (m002) and away (m003) against Perth Glory ([screenshot](img/compare_brisbane_perth.png)) |
| - | Orchestration with Dagster: asset graph, a sensor on the end of a match, a schedule, retries, a failed check blocks what follows | stack | both | done: `dagster/` (bronze -> Silver -> Soda Silver -> dbt Gold -> Soda Gold -> report, partitioned by match), sensor `replay_end`, nightly Soda schedule, 2 retries on Spark and dbt, pool `duckdb` (one Gold build at a time); pages Pipeline & lineage and Sources & limits; 7 Dagster tests + 6 page tests | `make dagster`, then `make replay MATCH=m001`: on 2026-11-16 the sensor started the run of each replay by itself ([asset graph](img/dagster_asset_graph.png)); with damaged data the Silver check failed (6 of 73) and Gold was not built, the Gold file unchanged ([run](img/dagster_damaged_run.png)); m003 and m001 ending 10 s apart: the second Gold waited for the pool ([run](img/dagster_pool_wait_run.png)); a re-run of m001 left the 16 Gold tables identical row by row (15,294 rows); `python -m pytest tests/dagster tests/app` |
| - | Replay of a stored match (product.md R1, S1) | stack | both | done: `gold_replay_frames` (17th Gold table, 6 Soda checks), the Replay page (pitch.js plays the match in the browser: 0.25x-8x, scrubber, goal marks, smooth movement between seconds, trails, names, detected only, Voronoi) and its panel up to the replay time; Live drawn in the same Silver frame | on 2026-11-16, m001: 110 positions drawn at 5 random seconds equal `silver.tracking` (largest difference 1.4e-14 m); Live and Replay at 6 seconds of both halves: 132 positions, difference 0; the panel at 24:59, half time and full time equals Gold (score, possession seconds, windows, tracked seconds, distance, sprints, top speed); the Goodwin chip shows 2-2, then 2-3 at 62:57 ([screenshot](img/replay_m001_after_goodwin.png)); payload 1.69-2.06 MB per match sent once; the whole of m001 at 8x with trails, names and Voronoi: 59-60 fps, browser heap 36-68 MB ([Voronoi](img/replay_m001_voronoi_goodwin.png), [full time](img/replay_m001_full_time.png)); `python -m pytest tests/app` |

Status: todo · in progress · done (with proof: command, file or screenshot).
## Data corrections (2026-11-17)

### Top speed (F5): best speed held over two consecutive detected seconds

Before: the fastest single second whose two positions the camera saw (m003: T. Okamoto 39.5 km/h, impossible).
After: `max(min(v(ts - 1), v(ts)))` with the positions of ts - 2, ts - 1 and ts detected, in `gold_player_card`,
Live and Replay (`playerstats.py`), shown on the Player page and the Match story. The after column, recomputed
here from Silver, equals `gold_player_card.top_speed_kmh` for all 123 players (to its 1 decimal).
Fastest overall: before 39.5 km/h, after 33.1 km/h; players above 36 km/h:
before 1, after 0.

**m001**

| # | 10 fastest before (km/h) | after | 10 fastest after (km/h) | before |
|---|---|---|---|---|
| 1 | C. Brown (LB) 33.0 | 25.6 | A. Goodwin (CF) 31.9 | 32.8 |
| 2 | A. Goodwin (CF) 32.8 | 31.9 | B. Folami (LW) 31.4 | 31.7 |
| 3 | D. Pierias (RB) 32.3 | 30.9 | B. Halloran (LW) 31.3 | 31.6 |
| 4 | A. Burke-Gilroy (RB) 31.7 | 30.6 | R. Kitto (LB) 31.2 | 31.6 |
| 5 | B. Folami (LW) 31.7 | 31.4 | D. Pierias (RB) 30.9 | 32.3 |
| 6 | R. Kitto (LB) 31.6 | 31.2 | S. Klein (RDM) 30.7 | 30.9 |
| 7 | B. Halloran (LW) 31.6 | 31.3 | A. Burke-Gilroy (RB) 30.6 | 31.7 |
| 8 | B. Warland (LCB) 31.6 | 27.9 | E. Alagich (LDM) 30.4 | 30.7 |
| 9 | S. Klein (RDM) 30.9 | 30.7 | H. Bility (RCB) 29.6 | 30.1 |
| 10 | F. Bérenguer (LW) 30.9 | 29.2 | T. Waddingham (CF) 29.4 | 30.8 |

**m002**

| # | 10 fastest before (km/h) | after | 10 fastest after (km/h) | before |
|---|---|---|---|---|
| 1 | A. Faisal (LW) 31.6 | 29.0 | H. Van Der Saag (RB) 29.1 | 31.4 |
| 2 | H. Van Der Saag (RB) 31.4 | 29.1 | A. Faisal (LW) 29.0 | 31.6 |
| 3 | J. Risdon (RB) 30.7 | 28.2 | A. Burke-Gilroy (LB) 28.3 | 29.1 |
| 4 | T. Ostler (RW) 29.9 | 27.2 | J. Risdon (RB) 28.2 | 30.7 |
| 5 | R. Warland (LB) 29.5 | 27.6 | N. Blair (CF) 27.9 | 28.4 |
| 6 | A. Burke-Gilroy (LB) 29.1 | 28.3 | T. Waddingham (CF) 27.9 | 28.0 |
| 7 | F. Bérenguer (AM) 28.9 | 26.2 | R. Warland (LB) 27.6 | 29.5 |
| 8 | N. Blair (CF) 28.4 | 27.9 | Walid Shour (RDM) 27.4 | 28.2 |
| 9 | N. Pennington (LM) 28.4 | 25.5 | K. Jelacic (LW) 27.3 | 27.7 |
| 10 | Walid Shour (RDM) 28.2 | 27.4 | A. Zimarino (RW) 27.3 | 27.5 |

**m003**

| # | 10 fastest before (km/h) | after | 10 fastest after (km/h) | before |
|---|---|---|---|---|
| 1 | T. Okamoto (RB) 39.5 | 31.3 | J. Anasmo (RW) 31.3 | 33.5 |
| 2 | J. Anasmo (RW) 33.5 | 31.3 | T. Okamoto (RB) 31.3 | 39.5 |
| 3 | K. Jelacic (CF) 32.9 | 27.8 | P. Wood (CF) 30.7 | 32.0 |
| 4 | P. Wood (CF) 32.0 | 30.7 | A. Burke-Gilroy (RB) 29.8 | 30.6 |
| 5 | N. Mileusnić (RW) 31.7 | 28.9 | B. Halloran (RW) 29.5 | 30.9 |
| 6 | B. Halloran (RW) 30.9 | 29.5 | N. Mileusnić (RW) 28.9 | 31.7 |
| 7 | A. Burke-Gilroy (RB) 30.6 | 29.8 | A. Taggart (CF) 28.9 | 30.4 |
| 8 | N. Amanatidis (CF) 30.4 | 27.6 | J. Hingert (RB) 28.7 | 29.6 |
| 9 | A. Taggart (CF) 30.4 | 28.9 | J. Pearman (CF) 28.5 | 30.1 |
| 10 | J. Pearman (CF) 30.1 | 28.5 | S. Klein (RM) 28.3 | 28.8 |

**m004**

| # | 10 fastest before (km/h) | after | 10 fastest after (km/h) | before |
|---|---|---|---|---|
| 1 | Z. Clough (RW) 34.3 | 33.1 | Z. Clough (RW) 33.1 | 34.3 |
| 2 | D. Pierias (RB) 33.4 | 33.0 | D. Pierias (RB) 33.0 | 33.4 |
| 3 | A. Segecic (RDM) 32.9 | 30.7 | P. Klimala (CF) 31.1 | 31.8 |
| 4 | P. Klimala (CF) 31.8 | 31.1 | A. Ayoubi (RW) 30.9 | 31.2 |
| 5 | A. Goodwin (CF) 31.7 | 30.3 | A. Segecic (RDM) 30.7 | 32.9 |
| 6 | A. Ayoubi (RW) 31.2 | 30.9 | A. Goodwin (CF) 30.3 | 31.7 |
| 7 | J. Courtney-Perkins (LB) 30.8 | 29.5 | J. Lolley (RW) 30.0 | 30.5 |
| 8 | J. Lolley (RW) 30.5 | 30.0 | R. Grant (RCB) 29.7 | 30.0 |
| 9 | A. Ouahim (LW) 30.2 | 29.2 | Z. de Jesus (RB) 29.7 | 29.8 |
| 10 | J. Yull (LW) 30.1 | 29.2 | A. Cáceres (AM) 29.6 | 30.0 |

### Goal moment: the second the ball was in the goal

A goal event's ts is the start of the possession that ended with the shot. Live and Replay now change the score
at `gold_events.goal_ts`: within 10 s, the first second with the ball past the goal line between the posts, else
the second the ball was nearest the goal mouth (the ball is extrapolated after many shots and the camera often
cuts away). The same rule in dbt and `app/streamlit/goalmoment.py` (Live): equal on the 15 goals. The minute of
a goal (6', 62') still comes from its ts: no minute changes.

| Match | Scorer | Old second (clock) | New second (clock) | Later by | How |
|---|---|---|---|---|---|
| m001 | K. Jelacic | 326 (05:26) | 330 (05:30) | 4 s | ball_in_goal |
| m001 | S. Mauk | 1934 (32:14) | 1936 (32:16) | 2 s | ball_in_goal |
| m001 | J. O'Shea | 2538 (42:18) | 2539 (42:19) | 1 s | ball_nearest_goal |
| m001 | Z. Clough | 2936 (45:37) | 2936 (45:37) | 0 s | ball_nearest_goal |
| m001 | A. Goodwin | 3890 (61:31) | 3892 (61:33) | 2 s | ball_in_goal |
| m002 | D. Williams | 4429 (68:25) | 4430 (68:26) | 1 s | ball_nearest_goal |
| m003 | L. Amos | 411 (06:51) | 414 (06:54) | 3 s | ball_nearest_goal |
| m003 | Asumah Abubakar | 2165 (36:05) | 2169 (36:09) | 4 s | ball_nearest_goal |
| m003 | S. Klein | 3194 (50:38) | 3196 (50:40) | 2 s | ball_in_goal |
| m003 | S. Klein | 5473 (88:37) | 5477 (88:41) | 4 s | ball_nearest_goal |
| m004 | J. Lolley | 2127 (35:27) | 2128 (35:28) | 1 s | ball_in_goal |
| m004 | P. Klimala | 2818 (45:16) | 2820 (45:18) | 2 s | ball_nearest_goal |
| m004 | D. Pierias | 3033 (48:51) | 3039 (48:57) | 6 s | ball_in_goal |
| m004 | A. Segecic | 4576 (74:34) | 4582 (74:40) | 6 s | ball_in_goal |
| m004 | A. Cáceres | 5073 (82:51) | 5080 (82:58) | 7 s | ball_in_goal |

Checked in a browser on 2026-11-17: every goal of m001 to m004 played from its chip at 4x; for all 15, the score is
the old one before the goal second, the GOAL! banner appears at it with the new score, the replay holds 3 s and
plays on ([m004](img/replay_goal_banner_m004.png), [m001](img/replay_goal_banner_m001.png)). Live, m001 from
05:12 at x1: 0-0 until 05:28, 1-0 at 05:29 ([screenshot](img/live_goal_moment_m001.png)). While playing, the
panel trails by a median of 1 s of match time at 4x and 8x (max 2 s, 95 samples each); 8 clicks on players at 8x
each selected the player in 0.4-0.6 s ([screenshot](img/replay_click_at_8x.png)).

## Dagster runs (2026-11-16)

Every match went through the automatic chain: each run below marked `sensor` started by itself when its replay sent
its last second. Steps in order: bronze, silver, soda_silver, gold (dbt), soda_gold, match_report; `+` passed,
`x` failed, `-` not run because a step or check before it failed.

| Started (UTC) | Run | Match | Trigger | Result | Minutes | Steps | Replay | Note |
|---|---|---|---|---|---|---|---|---|
| 14:21:53 | a4ef3d8a | m001 | sensor | failure | 2.2 | `++x` | m001-20261116T141951Z | bug 1 below |
| 14:28:11 | 7852ff43 | m001 | sensor | success | 3.8 | `++++++` | m001-20261116T142608Z | first green automatic run |
| 14:34:01 | ab6adb0d | m001 | manual | failure | 2.4 | `++x---` | | damaged-data demo: the Silver check fails on purpose, Gold is not built |
| 14:40:21 | 87696e9e | m001 | manual | success | 3.7 | `++++++` | | re-run: the 16 Gold tables identical row by row |
| 14:46:18 | 18bf663e | m003 | sensor | failure | 7.5 | `+x----` | m003-20261116T144424Z | bug 2 below (Silver failed after its 2 retries) |
| 14:46:38 | 5fdb45de | m001 | sensor | success | 5.3 | `++++++` | m001-20261116T144434Z | |
| 15:02:59 | 66d72256 | m003 | sensor | success | 5.5 | `++++++` | m003-20261116T150105Z | ended 10 s before the next one |
| 15:03:14 | 740a654f | m001 | sensor | success | 5.3 | `++++++` | m001-20261116T150115Z | its Gold step waited for the `duckdb` pool (15:06:12 to 15:07:03) |
| 15:28:38 | e9333502 | m002 | sensor | success | 5.4 | `++++++` | m002-20261116T152636Z | |
| 15:30:20 | 134bc892 | m004 | sensor | success | 5.3 | `++++++` | m004-20261116T152820Z | |

The two failures and their fixes:

1. **The Soda Silver check could not read its configuration** (`AssetCheckExecutionContext` has no `op_config`). Fixed by
   reading it through `context.op_execution_context`; `tests/dagster` now runs both Soda checks through the nightly job
   with and without damage, which would have caught it.
2. **Silver refused m003 after its third replay**: its gate compared the 4 rejected speeds (after deduplication) with
   the 12 bronze rows above 40 km/h counted before deduplication, one copy per replay. Fixed in Silver (commit
   `a654aea`): the bronze rows are counted once per key, the key Silver deduplicates on; a Spark test replays a rejected
   speed twice.

## External check against official sources

Goal minutes come from `clock.py` (football clock: the second half restarts at 45:00 from its own kick-off,
`p2_start_ts`, which is exactly the kick-off frame of `match.json`: m001 frame 29000 = ts 2899, m002 frame 30250 = ts
3024). Possession is ours from `gold_team_profile.possession_share`.

What the official sources say (club reports, AAP, Fox Sports, ESPN, FBref, with links) is in
[`external_checks.yml`](external_checks.yml), the one source of these facts, checked on 2026-11-17. The Data quality page
(Accuracy) and the Sources & limits page compare them with Gold every time they open: 15 of 15 goal minutes the same as
at least one source (sources disagree with each other: Goodwin 62' or 63', Klein 50' or 51'), possession within 1 point
of a source for m001 to m003 and within 2 for m004 (ESPN 54 %, ours 52.5 %).

Tested in `tests/app/test_clock.py` (m001 goals, stoppage time, the running clock, 5-minute windows).
