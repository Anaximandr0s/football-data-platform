# Requirements coverage

| Ref | Requirement | Type | Owner | Status | Proof |
|---|---|---|---|---|---|
| FOO-01 | A full match: 22 players, 1 position per second, at least 1,000 actions | OBL | ingestion | done (real data instead of generated: confirm with the professor) | `make data`: m001 22 players per second, 1,741 events; m002 1,878 events |
| FOO-02 | Live replay through Kafka at x1 to x60 | OBL | ingestion | done at x60 (x1 to x60 supported) | `make replay`: 100 s for m001, `make counts` |
| FOO-03 | Silver Iceberg table, grain player x second | OBL | Silver / Gold | in progress: code and 13 unit tests done; Iceberg write not yet run on MinIO | `python -m pytest tests/spark`; `make silver MATCH=m001 ARGS=--dry-run` report (counts equal `silver-guide.md`); then add the real `make silver` run |
| FOO-04 | Gold per player: distance, sprints, max speed, actions by type | OBL | Silver / Gold | done: `gold_player_match_stats` and 14 other Gold tables (the 9 MatchLens tables of `product.md` section 7 included), 16 pytest; run on MinIO for m001 and m002 | `make gold` on 2026-11-15: PASS=84 ERROR=0 (dbt models and tests); 27 numbers of the new tables recomputed in pandas from the Silver Parquet, all equal; the 6 first tables identical before and after the new ones (row-by-row diff = 0); `python -m pytest tests/dbt` |
| FOO-05 | Checks: inside the pitch, speed <= 40, 22 players per second | OBL | Silver / Gold | done: 73 Silver + 136 Gold Soda checks, failure demo, 15 tests; run on MinIO for m001 and m002 | `make soda` on 2026-11-16 (4 matches): silver 73 passed, gold 130 passed, 0 failed; `python -m pytest tests/soda` in the Soda environment; `make soda-demo`: 6 Silver checks and 1 Gold check fail on the injected damage, exit 0 |
| FOO-06 | Streamlit pitch with live positions and score | OBL | both | done: page Live match (pitch, score from goal events, clock, possession, last event, team shape of the current second, camera-gap message); 8 state tests + 3 headless page tests | `make app`, then `make replay MATCH=m001 SPEED=5` while the page is open: on 2026-11-15 it showed 1-0 after the first goal, 2-3 after the fifth ([screenshot](img/live_match_m001_goal5.png)), "No tracking: camera off the pitch" inside the 143 s gap, and 2-3 at full time; `python -m pytest tests/app` |
| FOO-07 | Streamlit heatmap of a player and shot maps | OBL | both | done: Player page (heatmap, shots and passes on the pitch component), Team analysis (shot map, pass network), Live heatmap so far; headless tests; seen in a browser on 2026-11-15 ([Player page](img/player_fan_m001.png), [coach mode](img/player_coach_m001.png), [Live](img/live_player_selected_m001.png)) | `make app`, Player page and Live match with a player clicked; `python -m pytest tests/app` |
| FOO-08 | 5-minute rolling stats with Spark Structured Streaming | OPT | Silver / Gold | done: `spark/streaming/` on the Spark cluster (3 queries, checkpoint on MinIO) writes the 5-min (F2, F4, F5) and 15-min (C3) windows of each replay to the compacted topic `foot-live-stats`; the Live page shows them as complete or in progress; 4 unit tests of the formulas and the completion rule | `make streaming`, then `make replay MATCH=m001 SPEED=10`; on 2026-11-16 the 506 rows of the replay (job stopped at minute 40 and restarted) and of an earlier x60 replay were complete and equal Gold value by value, and so were the 502 rows of m003 at x60; the demo run (m001 at x1 from 04:56, 10 minutes) shows 0-5' and 5-10' complete and 10-15' in progress ([screenshot](img/live_5min_panel_m001_x1.png)) (only 0.1 m .x5 rounding ties, unrounded sums checked equal) ([Spark UI](img/spark_ui_streaming.png), [Live](img/live_5min_panel_m001.png)); `python -m pytest tests/spark tests/app` |
| FOO-09 | Compare two matches, or cluster player profiles | OPT | Silver / Gold | done for comparing (clustering not done): Compare matches shows one team in any of its stored matches, venue and opponent named, with sentences checked against Gold | `make app`, Compare matches: Brisbane Roar at home (m002) and away (m003) against Perth Glory ([screenshot](img/compare_brisbane_perth.png)) |
| - | Orchestration with Dagster: asset graph, a sensor on the end of a match, a schedule, retries, a failed check blocks what follows | stack | both | done: `dagster/` (bronze -> Silver -> Soda Silver -> dbt Gold -> Soda Gold -> report, partitioned by match), sensor `replay_end`, nightly Soda schedule, 2 retries on Spark and dbt, pool `duckdb` (one Gold build at a time); pages Pipeline & lineage and Sources & limits; 7 Dagster tests + 6 page tests | `make dagster`, then `make replay MATCH=m001`: on 2026-11-16 the sensor started the run of each replay by itself ([asset graph](img/dagster_asset_graph.png)); with damaged data the Silver check failed (6 of 73) and Gold was not built, the Gold file unchanged ([run](img/dagster_damaged_run.png)); m003 and m001 ending 10 s apart: the second Gold waited for the pool ([run](img/dagster_pool_wait_run.png)); a re-run of m001 left the 16 Gold tables identical row by row (15,294 rows); `python -m pytest tests/dagster tests/app` |
| - | Replay of a stored match (product.md R1, S1) | stack | both | done: `gold_replay_frames` (17th Gold table, 6 Soda checks), the Replay page (pitch.js plays the match in the browser: 0.25x-8x, scrubber, goal marks, smooth movement between seconds, trails, names, detected only, Voronoi) and its panel up to the replay time; Live drawn in the same Silver frame | on 2026-11-16, m001: 110 positions drawn at 5 random seconds equal `silver.tracking` (largest difference 1.4e-14 m); Live and Replay at 6 seconds of both halves: 132 positions, difference 0; the panel at 24:59, half time and full time equals Gold (score, possession seconds, windows, tracked seconds, distance, sprints, top speed); the Goodwin chip shows 2-2, then 2-3 at 62:57 ([screenshot](img/replay_m001_after_goodwin.png)); payload 1.69-2.06 MB per match sent once; the whole of m001 at 8x with trails, names and Voronoi: 59-60 fps, browser heap 36-68 MB ([Voronoi](img/replay_m001_voronoi_goodwin.png), [full time](img/replay_m001_full_time.png)); `python -m pytest tests/app` |

Status: todo · in progress · done (with proof: command, file or screenshot).
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
3024). Possession is ours from `gold_team_profile.possession_share`. Checked on 2026-11-15.

| Match | Ours | Official source | Agrees |
|---|---|---|---|
| m001 Brisbane Roar 2-3 Adelaide United, goals | 6' Jelacic, 33' Mauk, 43' O'Shea, 46' Clough, 62' Goodwin | [Brisbane Roar match wrap](https://brisbaneroar.com.au/news/alm-united-round-match-wrap-brisbane-roar-2-3-adelaide-united/): 6', 33', 43', 46', 63' | 4 of 5 exact; Goodwin one minute apart: his shot is 16:31.8 into the second half in the data (the 62nd minute); the club writes 63' |
| m001 possession | Brisbane Roar 40 %, Adelaide United 60 % | [FBref match report](https://fbref.com/en/matches/9d2e447a/Brisbane-Roar-Adelaide-United): 39 % / 61 % | yes, within 1 point |
| m002 Brisbane Roar 0-1 Perth Glory, goal | 69' Williams | [Brisbane Roar match wrap](https://brisbaneroar.com.au/news/alm-r9-match-wrap-brisbane-roar-0-1-perth-glory/), [AAP](https://aapnews.aap.com.au/news/glory-defeat-roar-to-end-18-game-alm-winless-streak): 69' (Perth Glory's own report: 70') | yes |
| m002 possession | Brisbane Roar 63 %, Perth Glory 37 % | [FBref match report](https://aws.fbref.com/en/matches/f328e2b6/Brisbane-Roar-Perth-Glory-December-21-2024-A-League-Men): 64 % for Brisbane | yes, within 1 point |
| m003 Perth Glory 1-3 Brisbane Roar (SkillCorner 2007448), goals | 7' Amos, 37' Abubakar, 51' Klein, 89' Klein | [Brisbane Roar match wrap](https://brisbaneroar.com.au/news/alm-r23-match-wrap-perth-glory-1-3-brisbane-roar): 7', 37', 50', 89' | 3 of 4 exact; Klein's first one minute apart (other reports give 51'). The second half's first data second (ts 2856) is 3 s after `match.json`'s kick-off frame (28540 = ts 2853): it changes no minute here |
| m004 Sydney FC 4-1 Adelaide United (SkillCorner 1996435), goals | 36' Lolley, 46' Klimala, 49' Pierias, 75' Segecic, 83' Cáceres | [AAP](https://aapnews.aap.com.au/news/lolley-hits-sweet-spot-as-sydney-slice-adelaide-apart), [Adelaide United report](https://adelaideunited.com.au/?p=329213): 36', 46', 49', 75', 83' | yes, 5 of 5 |
| m003 possession | Perth Glory 50 %, Brisbane Roar 50 % | [FBref match report](https://aws.fbref.com/en/matches/257b3ee8/Perth-Glory-Brisbane-Roar-March-15-2025-A-League-Men): 50 % / 50 % | yes, exact |
| m004 possession | Sydney FC 52.5 %, Adelaide United 47.5 % | FBref report not reachable; [ESPN](https://www.espn.com/soccer/match/_/gameId/718012/adelaide-united-sydney-fc): 54 % / 46 % | within 2 points |

Tested in `tests/app/test_clock.py` (m001 goals, stoppage time, the running clock, 5-minute windows).
