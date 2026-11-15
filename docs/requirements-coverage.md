# Requirements coverage

| Ref | Requirement | Type | Owner | Status | Proof |
|---|---|---|---|---|---|
| FOO-01 | A full match: 22 players, 1 position per second, at least 1,000 actions | OBL | ingestion | done (real data instead of generated: confirm with the professor) | `make data`: m001 22 players per second, 1,741 events; m002 1,878 events |
| FOO-02 | Live replay through Kafka at x1 to x60 | OBL | ingestion | done at x60 (x1 to x60 supported) | `make replay`: 100 s for m001, `make counts` |
| FOO-03 | Silver Iceberg table, grain player x second | OBL | Silver / Gold | in progress: code and 13 unit tests done; Iceberg write not yet run on MinIO | `python -m pytest tests/spark`; `make silver MATCH=m001 ARGS=--dry-run` report (counts equal `silver-guide.md`); then add the real `make silver` run |
| FOO-04 | Gold per player: distance, sprints, max speed, actions by type | OBL | Silver / Gold | done: `gold_player_match_stats` and 14 other Gold tables (the 9 MatchLens tables of `product.md` section 7 included), 16 pytest; run on MinIO for m001 and m002 | `make gold` on 2026-11-15: PASS=84 ERROR=0 (dbt models and tests); 27 numbers of the new tables recomputed in pandas from the Silver Parquet, all equal; the 6 first tables identical before and after the new ones (row-by-row diff = 0); `python -m pytest tests/dbt` |
| FOO-05 | Checks: inside the pitch, speed <= 40, 22 players per second | OBL | Silver / Gold | done: 71 Silver + 127 Gold Soda checks, failure demo, 15 tests; run on MinIO for m001 and m002 | `make soda` on 2026-11-15: silver 71 passed, gold 127 passed, 0 failed; `python -m pytest tests/soda` in the Soda environment; `make soda-demo`: 6 Silver checks and 1 Gold check fail on the injected damage, exit 0 |
| FOO-06 | Streamlit pitch with live positions and score | OBL | both | done: page Live match (pitch, score from goal events, clock, possession, last event, team shape of the current second, camera-gap message); 8 state tests + 3 headless page tests | `make app`, then `make replay MATCH=m001 SPEED=5` while the page is open: on 2026-11-15 it showed 1-0 after the first goal, 2-3 after the fifth ([screenshot](img/live_match_m001_goal5.png)), "No tracking: camera off the pitch" inside the 143 s gap, and 2-3 at full time; `python -m pytest tests/app` |
| FOO-07 | Streamlit heatmap of a player and shot maps | OBL | both | done: Player page (heatmap, shots and passes on the pitch component), Team analysis (shot map, pass network), Live heatmap so far; headless tests; seen in a browser on 2026-11-15 ([Player page](img/player_fan_m001.png), [coach mode](img/player_coach_m001.png), [Live](img/live_player_selected_m001.png)) | `make app`, Player page and Live match with a player clicked; `python -m pytest tests/app` |
| FOO-08 | 5-minute rolling stats with Spark Structured Streaming | OPT | Silver / Gold | todo | |
| FOO-09 | Compare two matches, or cluster player profiles | OPT | Silver / Gold | in progress: team-level compare page done (clustering not done) | `make app`, page Compare matches (to add a screenshot) |

Status: todo · in progress · done (with proof: command, file or screenshot).
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

Tested in `tests/app/test_clock.py` (m001 goals, stoppage time, the running clock, 5-minute windows).
