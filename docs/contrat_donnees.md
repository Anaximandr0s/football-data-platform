# Data contract: ingestion, Silver and Gold (source -> Kafka -> bronze -> Silver -> Gold)

Owner of sections 1 to 8: ingestion (Kafka, MinIO, bronze). Consumers: Silver (Spark + Iceberg), then Gold and Streamlit.
Sections 9 (Silver) and 10 (Gold) have their own owners and code twins, given at the top of each section.
The code twin of the table sections is `ingestion/schemas.py` (`SCHEMAS`): change both together, by pull request,
and warn the Silver owner. Last update: 2026-11-16 (Kafka header `replay_id`, bronze column `kafka_replay_id` and topic `foot-live-stats`, in sections 5, 6 and 9.2). Before: 2026-11-15 (possession on ball, `source_player_id` on players, `is_detected` on tracking, event context columns and off-ball runs as type `run`, in sections 4 to 9). Matches covered: `m001` (SkillCorner 1874553) and `m002` (SkillCorner 1925299).

## 1. Provenance

- Source: SkillCorner open data (MIT licence): real broadcast-tracking data of two A-League matches,
  downloaded by `ingestion/download_foot.py` into `data/raw/skillcorner/<id>/` (git-ignored, about 100 MB per match).
  Credit SkillCorner in the app and the report.
- Three raw files are used per match: `<id>_match.json` (lineups, teams, league, score, periods, pitch),
  `<id>_tracking_extrapolated.jsonl` (10 frames per second: ball and players),
  `<id>_dynamic_events.csv` (300+ columns, 4 event families).
- Names of players, teams and league are kept as in the source (school project, permission to display them).
  Player photos are not used. Players get match-local technical ids `H01..` / `A01..`; teams are keyed `HOME` / `AWAY`.
- `ingestion/ingest_foot.py` converts the raw files into 5 Parquet tables in `data/prepared/<match_id>/` plus a
  `manifest.json` (counts and quality indicators). `ingestion/producer_foot.py` replays them into Kafka.

## 2. Conventions

| Item | Rule |
|---|---|
| Pitch | 105 x 68 m, origin bottom-left, `x` in [0, 105] along the long side, `y` in [0, 68], metres |
| `ts` | integer seconds since kick-off: `ts = (source frame - first frame) // 10`; continuous across halves (no half-time gap) |
| `period` | 1 or 2, as given by the source |
| `team_id` | `HOME` or `AWAY`; the real names are in `matches` |
| `player_id` | `H01..H16`, `A01..A16`, ordered by time of entry on the pitch, then shirt number. **Match-local**: `H01` in two matches is two different people; `players.source_player_id` (the SkillCorner id) is the same person across matches |
| `match_id` | `m001`, `m002` (our id; the SkillCorner id is only in `manifest.json`) |
| Null | missing value (never 0, never an empty string) |
| Attack direction | NOT normalised. `matches.home_side_p1/p2` says where HOME attacks (`left_to_right` = toward x = 105). In m001 HOME attacks toward x = 105 in period 1 and toward x = 0 in period 2 |

## 3. What ingestion does, and what it does not

Done: 10 Hz -> 1 Hz (1 frame in 10), one row per player per second, only players on the pitch (from each player's
playing time, so substitutions are handled), origin moved to bottom-left, technical player ids, speed derived from
positions, events mapped to our vocabulary.

NOT done (Silver's job): clipping or fixing positions, smoothing speeds, flipping directions, filling gaps,
deduplication, any business rule.

## 4. Tables

### tracking: one row = one player at one second, players on the pitch only

| Column | Type | Null | Meaning |
|---|---|---|---|
| match_id | string | no | |
| player_id | string | no | |
| ts | int32 | no | second since kick-off |
| period | int8 | no | 1 or 2 |
| x, y | float64 | no | position in metres, 2 decimals; may lie slightly outside the pitch |
| speed_kmh | float64 | yes | distance to the player's position at `ts - 1`, times 3.6. Null when that previous row does not exist (first second of a stretch, after a gap, after a substitution). Not smoothed, not capped; a 1-second chord, so it under-estimates peaks |
| is_detected | bool | no | the camera saw the player in this frame; false = position estimated by SkillCorner (about 42 % of the rows) |

Key: (match_id, player_id, ts). Not every second exists (section 7).

### events: one row = one game action, or one off-ball run (type `run`)

| Column | Type | Null | Meaning |
|---|---|---|---|
| match_id, event_id | string | no | actions: `<match_id>-e00001`..., runs: `<match_id>-r00001`..., each sequence numbered after sorting by `ts`. Actions keep the ids they had before runs were added |
| ts, period | int32, int8 | no | second of the start of the action |
| player_id, team_id | string | no | player who performs the action, and his team |
| receiver_id | string | yes | for a pass: the teammate it was aimed at; null for other types or if unknown |
| type | string | no | actions: `pass`, `shot`, `goal`, `tackle`, `foul`, `pressure` (no corner in this source); `run` = an off-ball run, **not an action**: never count it with them. A goal is a `goal`, not a `shot`: shot map = shot + goal |
| x_start, y_start | float64 | yes | where the action starts |
| x_end, y_end | float64 | yes | pass: where the receiver got the ball when known, else the end of the possession; other types: end of the action as given by the source |
| outcome | string | no | text copied from the source: pass outcome (e.g. `successful`), else how the action ended (e.g. `direct_regain`, `foul_committed`, `shot`), `n/a` if none (always for runs). Profile the real list in Silver |
| phase | string | yes | phase of play of the team in possession: `build_up`, `create`, `finish`, `direct`, `quick_break`, `transition`, `set_play`, `chaotic`, `disruption` |
| phase_against | string | yes | the same moment seen by the team without the ball: `high_block`, `medium_block`, `low_block`, `defending_*`, `chaotic`, `disruption` |
| xthreat | float64 | yes | SkillCorner xThreat. Pass: of the option it aimed at (`player_targeted_xthreat`, about 95 % filled); run: of the run; null for other types. Not xG |
| dangerous | bool | yes | SkillCorner danger flag, same rows as `xthreat` |
| speed_band | string | yes | `jogging`, `running`, `hsr`, `sprinting` (average speed of the action) |
| subtype | string | yes | engagements (`pressure`, `tackle`, `foul`): `pressure`, `recovery_press`, `pressing`, `counter_press`, `other`; runs: `run_ahead_of_the_ball`, `support`, `coming_short`, `behind`, `dropping_off`, `pulling_wide`, `cross_receiver`, `overlap`, `underlap`, `pulling_half_space`; null otherwise |
| lead_to_shot | bool | yes | the possession this event belongs to ended in a shot |
| targeted, received | bool | yes | runs only (null on actions): the run was aimed at by a pass, and the pass reached it |

Derivations: `pass` / `shot` come from `player_possession` rows ending in a pass or a shot; `pressure`, `tackle`, `foul`
from `on_ball_engagement` rows; `goal` = the last shot of a team before its score increases (checked against the real
score for both matches); `run` from `off_ball_run` rows. `passing_option` rows are not kept.

### ball: one row = the ball at one second

`match_id` (string), `ts` (int32), `period` (int8), `x`, `y`, `z` (float64, metres; `z` = height), `possession` (string,
`HOME`, `AWAY` or null when the ball is dead or nobody controls it; from the tracking frame's `possession.group`).
Only seconds where the source has a ball position exist, so possession known in a second without a ball position is
not kept (55 seconds in m001, 50 in m002, all of them gap seconds without any player either; section 7).

### players: one row = one player of the match (starters and substitutes who played)

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id | string | |
| name | string | full name as in the source |
| short_name | string | label form, e.g. `J. Caletti` (some are not shortened by the source) |
| position | string | source acronym of the role played (GK, RCB, AM...) |
| shirt_number | int32 | |
| start_ts, end_ts | int32 | first and last second on the pitch; starters have `start_ts` = 0 |
| source_player_id | int64 | SkillCorner player id: the same person across matches (11 Brisbane Roar players played both m001 and m002) |

Substitutes who never played are not listed.

### matches: one row = one match

| Column | Type | Meaning |
|---|---|---|
| match_id | string | |
| competition, season, round | string | league name, e.g. `2024/2025`, `Round 5`; may be null |
| kickoff_utc | string | ISO timestamp as in the source; may be null |
| stadium | string | may be null |
| home_team, away_team | string | full team names |
| home_team_short, away_team_short | string | short names |
| home_color, away_color | string | kit colour, hex like `#363636`; may be null or similar for both teams |
| home_score, away_score | int32 | final score |
| pitch_length, pitch_width | float64 | always 105 x 68 on this platform |
| p1_start_ts, p1_end_ts, p2_start_ts, p2_end_ts | int32 | first and last second WITH DATA of each period |
| home_side_p1, home_side_p2 | string | `left_to_right` or `right_to_left`: direction HOME attacks |

## 5. Kafka

| Topic | Key | Partitions | Content | Order |
|---|---|---|---|---|
| foot-tracking | player_id | 3 | tracking | kept per player (all rows of one player share a partition) |
| foot-events | match_id | 1 | events | total |
| foot-ball | match_id | 1 | ball | total |
| foot-players | player_id | 1 | players | |
| foot-matches | match_id | 1 | matches | |
| foot-live-stats | see 5.1 | 1, compacted | live stats of the streaming job (FOO-08) | per key |

Messages are JSON, one row each, with the column names above. `matches` and `players` are sent at the start of each
replay, then the live tables second by second. Replay speed x1 to x60 (x60: a match lasts about 100 s).

Every message of a replay carries the Kafka header `replay_id` = `<match_id>-<start time UTC, YYYYMMDDTHHMMSSZ>`, for
example `m001-20261116T101503Z`, set once when `producer_foot` starts. Two replays of the same match have two ids, so the
Live page and the streaming job never mix them; for one match, a larger id is a newer replay. A message without the
header (written before 2026-11-16) is ignored by both.

### 5.1 foot-live-stats (written by `spark/streaming`, read by the Live page)

Log-compacted (`cleanup.policy=compact`): Kafka keeps at least the latest message of each key. Key =
`replay_id|match_id|window_size|window_index|player_id or team_id`. Value = JSON of one window, the **full current
value, never an increment**: a new message for the same key replaces the previous one. Built by
`spark/streaming/rows.py`, with the names and formulas of Gold.

| `kind` | Window | Grain | Values (same names as the Gold table) |
|---|---|---|---|
| `team` | 5 min | team x window | `gold_match_timeline`: possession_seconds, known_seconds, possession_share, possession_greyed, passes, defensive_actions; plus opponent_passes, ppp, ppp_greyed |
| `player` | 5 min | player x window | `gold_player_5min`: tracked_seconds, coverage, distance_m, sprint_seconds, max_speed_kmh |
| `pressing` | 15 min | team x window | `gold_pressing`: defensive_actions, opponent_passes, ppp, ppp_greyed, defensive_actions_own/middle/final_third, high_press_share |

Every row also has replay_id, match_id, team_id, window_size (300 or 900 s), window_index, window_label,
window_start_ts, window_end_ts (exclusive), window_seconds, last_ts (latest second counted), p2_end_ts, `complete`
and updated_at (ms). A window is **complete** when the replay's tracking has reached `window_end_ts + 10` (10 s of
match time of grace for messages of other topics that arrive late) or the last second of the match (`p2_end_ts`).
Only a complete window equals Gold; the Live page shows the others as "in progress".

## 6. Bronze (MinIO)

Path: `s3://bronze/<table>/match_id=<id>/ingest_date=<YYYY-MM-DD>/part-<epoch_ms>-<n>.parquet`, with `<table>` in
tracking, events, ball, players, matches. `ingest_date` is the UTC day of writing and exists only in the path.
Columns = the table columns (fixed types) plus `kafka_partition` (int32), `kafka_offset` (int64), `kafka_ts` (int64, ms),
`ingested_at` (int64, ms) and `kafka_replay_id` (string, the `replay_id` header of section 5; null for rows written
before 2026-11-16).

Delivery is at-least-once: a replay, or a consumer restart, adds duplicates. Silver deduplicates on: tracking
(match_id, player_id, ts); events `event_id`; ball (match_id, ts); players (match_id, player_id); matches `match_id`.
Files are micro-batches (about 10 s of arrival, at most 5,000 rows): row order inside and across files is NOT
chronological. Sort by (player_id, ts). `make check MATCH=<id>` compares bronze with the prepared files.
Files written before a column was added do not have it: Silver reads a match folder with `mergeSchema`, so those rows
read the column as null, and deduplication keeps the latest copy. A match must be replayed after a contract change.

## 7. Known characteristics (measured, one replay each)

| Item | m001 (SkillCorner 1874553) | m002 (SkillCorner 1925299) |
|---|---|---|
| Teams (home v away) | Brisbane Roar FC v Adelaide United Football Club | Brisbane Roar FC v Perth Glory Football Club |
| Players | 32 | 32 |
| Last second (`ts`) | 6025 | 6128 |
| Seconds with data | 4,428 of 6,030 (73.4%) | 4,797 of 6,130 (78.2%) |
| Gaps (runs) / longest | 63 / 143 s | 53 / 138 s |
| Tracking rows | 97,416 (22 x 4,428) | 105,534 (22 x 4,797) |
| Ball rows | 4,428 | 4,797 |
| Events (actions + runs) | 2,276 (1,741 + 535) | 2,376 (1,878 + 498) |
| By type | pass 837, pressure 835, tackle 36, shot 21, foul 7, goal 5, run 535 | pass 912, pressure 890, tackle 35, shot 29, foul 11, goal 1, run 498 |
| Detected tracking rows | 56,390 (57.9 %) | 61,162 (58.0 %) |
| Ball seconds with possession (HOME / AWAY) | 3,232 (1,277 / 1,955) | 3,510 (2,208 / 1,302) |
| Possession seconds lost (known limit) | 55 of 3,287 (1.7 %) | 50 of 3,560 (1.4 %) |
| Goals home-away | 2-3 (= real score) | 0-1 (= real score) |
| Rows outside the pitch | 735 (0.75%) | 618 |
| Rows with null speed | 1,386 | 1,166 |
| Rows above 40 km/h | 0 | 0 |

**Known limit: lost possession seconds.** The source knows which team has the ball in some seconds where it has no ball
position and no player (camera off the pitch). `ball` has no row for those seconds, so their possession is lost: 55
seconds in m001, 50 in m002. Possession shares computed from `ball` cover the other 98 % of the possession time.

Gaps are a property of the source, not of a match: the 20 matches of the SkillCorner repository have between 66% and
81% coverage (details in `data-sources.md`).

## 8. Who fixes what

| Issue | Where | Owner |
|---|---|---|
| Duplicates (replays) | Silver | Silver |
| Positions outside 105 x 68 | Silver, flag `was_corrected` | Silver |
| Attack direction flip (period 2 in m001) | Silver, using `matches.home_side_*` | Silver |
| Missing seconds / null speed | Silver: decide a gap policy, never replace by 0 | Silver |
| `team_id` on tracking | Silver: join `players` | Silver |
| Sprint detection (> 25 km/h) | Silver | Silver |
| 22 players per existing second, inside the pitch, speed <= 40 | Soda on Silver | Silver / Gold |
| Counts bronze = prepared | `make check MATCH=<id>` | ingestion |

## 9. Silver (Iceberg tables written by `spark/silver`)

Owner: Silver. Consumers: Gold (dbt), Soda, and the dashboard through Gold. Code twins: `spark/silver/transforms.py` (the
`select` of each `clean_*` function) and the schema checks of `soda/checks/silver.yml`: change the three together, by
pull request, and warn the Gold owner. Rules and decisions: [`silver-guide.md`](silver-guide.md) and
[`../spark/silver/README.md`](../spark/silver/README.md).

### 9.1 Where and how

- Iceberg tables `lake.silver.tracking`, `events`, `ball`, `players`, `matches` (Hadoop catalog, warehouse
  `s3://silver/warehouse`, files in `s3://silver/warehouse/silver/<table>/`), format version 2, partitioned by `match_id`.
  Catalog, namespace and warehouse are settable (`SILVER_CATALOG`, `SILVER_NAMESPACE`, `SILVER_WAREHOUSE`).
- Written one match at a time by `make silver MATCH=<id>`. A run replaces the partition of its match: running it again gives
  the same tables, other matches are untouched. A match is not written if its checks fail (counts, keys, goals = score).

### 9.2 What Silver changes compared with bronze

| Item | Bronze | Silver |
|---|---|---|
| Duplicates | possible (at-least-once delivery) | none: one row per key (section 6), the latest written copy is kept |
| Kafka columns (`kafka_partition`, `kafka_offset`, `kafka_ts`, `ingested_at`, `kafka_replay_id`) | present | removed |
| Row order | arrival order | tracking by (`player_id`, `ts`), events by (`ts`, `event_id`), ball by `ts` |
| `team_id` on tracking | absent | added from `players` (never null) |
| Attack direction | not normalised | **tracking and ball: HOME attacks toward x = 105 in both halves** (period mirrored where `home_side_pN` is `right_to_left`: x = 105 - x, y = 68 - y, both teams). **Events: per team** (see 9.3) |
| Positions outside the pitch | kept | **tracking only**: clipped to x in [0, 105], y in [0, 68], with `was_corrected` = true on the rows that were outside. Ball and events are not clipped (the ball really leaves the pitch, a shot can end behind the goal line) |
| `speed_kmh` | derived, may be null | null stays null (never 0); a speed above 40 km/h becomes null (a jump from an estimated position: 4 seconds in m003, none in m001, m002, m004); not recomputed after clipping |
| Gaps (missing seconds) | present | present: nothing is invented. `is_after_gap` marks the first second after one |
| `period` type | int8 | int32 |

### 9.3 Tables

Frame of every coordinate: pitch 105 x 68 m, origin bottom-left. HOME attacks toward x = 105 and AWAY toward x = 0 in both
halves. In `events` the source already gives the acting team attacking toward x = 105; Silver mirrors the AWAY events only
(`per_team`), so events and tracking share one frame (measured on m001: an event starts about 1 m from its player's tracking position).

**tracking**: one row = one player at one second (tracked seconds only). Key (match_id, player_id, ts).

| Column | Type | Null | Meaning |
|---|---|---|---|
| match_id, player_id | string | no | as in bronze (`H01`.. / `A01`.., match-local) |
| team_id | string | no | `HOME` or `AWAY` |
| period | int32 | no | 1 or 2 |
| ts | int32 | no | second since kick-off |
| x, y | float64 | no | metres, 2 decimals, inside the pitch (clipped), Silver frame |
| speed_kmh | float64 | yes | as in bronze: distance to the position at `ts - 1`, times 3.6. Null on the first second of a stretch, and above 40 km/h (impossible for a player: Silver sets it to null, its gate counts them against bronze) |
| speed_rejected | boolean | no | true where bronze had a speed above 40 km/h: the speed is set to null (a jump from a position SkillCorner estimated; m003: 4 rows). Rule: `speed_rejected` implies `speed_kmh` is null (Soda); their count equals the bronze rows above 40 km/h (Silver job gate) |
| is_sprint | bool | no | `speed_kmh > 25`; false when the speed is null |
| was_corrected | bool | no | the position delivered by bronze was outside 105 x 68 (before clipping) |
| is_after_gap | bool | no | the player's previous tracked second is more than 1 s earlier. False for a player's first row (nothing is missing before it) |
| is_detected | bool | no | as in bronze |

**events**: one row = one game action or one off-ball run. Key `event_id`. Columns, types and meanings as in section 4
(`match_id, event_id, ts, period, player_id, receiver_id, team_id, type, x_start, y_start, x_end, y_end, outcome, phase,
phase_against, xthreat, dangerous, speed_band, subtype, lead_to_shot, targeted, received`, `period` is int32), except:
coordinates are in the Silver frame (9.3 intro) and are not clipped. Runs follow the same per-team frame (measured: they
end 60 to 71 m toward the attacked goal on average, for both teams of both matches). Pass `outcome` values seen: `successful`,
`unsuccessful`, `offside`. Every pass of the two matches has a `receiver_id`.

**ball**: `match_id, ts, period, x, y, z, possession` as in section 4, `period` int32, x and y in the Silver frame, not clipped
(`possession` is a team, so it is not mirrored). One row per second with a ball position.

**players**, **matches**: the columns of section 4 without the Kafka columns, one row per player or match. `home_side_p1/p2`
keep their bronze meaning (where HOME attacked in the source); they are no longer needed to read positions.

### 9.4 Guarantees (each one is a Soda check on every `make soda`)

One row per key in every table · no null in keys, team, coordinates and flags · `team_id` is `HOME` or `AWAY`, `period` 1 or 2
· every tracking row and event belongs to a player of `players` with the same team · tracking inside the player's playing
time · exactly 22 tracking rows in every existing second · tracking inside 105 x 68 · speed in [0, 40] or null · `is_sprint`
equals (`speed_kmh` > 25) · event types in {pass, shot, goal, tackle, foul, pressure, run} · run fields only on runs, no
receiver on a run · possession `HOME`, `AWAY` or null · `source_player_id` present and unique per match · goals in events =
`home_score + away_score` · HOME shots toward x = 105 and AWAY shots toward x = 0 · row counts equal the table of the Silver guide (actions and runs counted separately).

### 9.5 Known characteristics (m001 measured through Silver; m002 from the ingestion figures of section 7)

| Item | m001 (SkillCorner 1874553) | m002 (SkillCorner 1925299) |
|---|---|---|
| Rows tracking / events (actions + runs) / ball / players / matches | 97,416 / 1,741 + 535 / 4,428 / 32 / 1 | 105,534 / 1,878 + 498 / 4,797 / 32 / 1 |
| `was_corrected` rows | 735 | 618 |
| Null `speed_kmh` | 1,386 (= 1,354 `is_after_gap` rows + 32 first rows) | 1,166 |
| `is_sprint` rows | 444 | to measure at the first run |
| `is_after_gap` rows | 1,354 | to measure at the first run |
| Goals home-away | 2-3 | 0-1 |

## 10. Gold (DuckDB tables built by dbt)

Owner: Gold. Consumers: the dashboard (`app/streamlit`), Soda, the post-match report. Code twins: `dbt/models/marts/*.sql` with
`dbt/models/marts/schema.yml`, and the schema checks of `soda/checks/gold.yml`: change them together, by pull request, and
warn the dashboard owner. Definitions and examples: [`../dbt/README.md`](../dbt/README.md); specification: [`gold-guide.md`](gold-guide.md).

### 10.1 Where and how

- DuckDB file `data/football.duckdb` (git-ignored), tables `main.gold_*`; copy as Parquet in `s3://gold/<table>.parquet`.
  The `stg_*` tables in the same file are copies of Silver used by dbt: they are not part of the contract.
- Rebuilt in full by `make gold` (dbt build): staging, intermediate models, 16 Gold tables, tests. Read it with `make gold-sql`
  or open it read-only. The `int_*` tables (`int_events`, `int_team_shape_second`, `int_space_control_second`) are inputs of
  several Gold tables: they are in the file but not exported and not part of the contract.

### 10.2 Conventions

| Item | Rule |
|---|---|
| Frame | the Silver frame: 105 x 68 m, origin bottom-left, HOME attacks toward x = 105, AWAY toward x = 0 |
| Keys | always (`match_id`, `player_id`): ids are match-local |
| Tracked time | distances, speeds, sprints and zones cover **tracked seconds only** (73 % to 78 % of a match) and come from 1 Hz positions: approximate, they under-estimate. Null speeds add nothing to a distance |
| Sprint | `speed_kmh > 25`. A **sprint effort** is a run of consecutive sprint seconds; a missing second ends it |
| Types | DuckDB: VARCHAR, INTEGER, BIGINT (counts), DOUBLE, BOOLEAN |
| Counts | a player with no event has 0, never null. Ratios and speeds are null when there is nothing to compute them from. Event counts cover actions only: a `run` is never counted and never creates a row (a 5-minute window with only runs has no row) |
| `shots` | type `shot` only. Goals are separate: shots on the shot map = shots + goals (`gold_shots` holds both) |
| Successful pass | `outcome = 'successful'` |
| Football windows | 5 and 15 minutes, restarting at each kick-off: index 0-8 then 9 (45+) in the first half, 10-18 then 19 (90+) in the second (15 minutes: 0-2, 3, 4-6, 7). Defined once by the dbt macro `football_window` and the table `int_football_windows`, the same rule as `clock.window_index` in the app; the stoppage window lasts until the end of its half |
| `x_att`, `y_att` | coordinates seen by the team of the row: `x_att` = `x` for HOME, `105 - x` for AWAY (distance from its own goal line); `y_att` = `y` for HOME, `68 - y` for AWAY (`y_att > 45.33` is its left) |
| Thirds, lanes | own `x_att < 35`, middle, final `x_att >= 70`; left `y_att > 45.33`, centre, right `y_att < 22.67` |
| Defensive action | `pressure`, `tackle` or `foul`; a `run` never counts |
| Progressive pass | a pass with `x_att(end) - x_att(start) >= 10` |
| Rates | `dpm` = distance / (seconds with a speed / 60), "per minute of tracked play (mostly ball in play)"; player per-minute values divide by the player's tracking rows / 60; team rates are per 90 minutes of the team's distinct tracked seconds |
| Eligibility | flags, never filters: a row below its threshold stays, with `is_eligible = false` or `possession_greyed = true`, and the app greys it out |
| Formulas | [`product.md`](product.md), sections 2 to 4 and 8.1 (ids F1-F8, C1-C7, S1, E1-E2) |

### 10.3 Tables

**gold_player_match_stats**: one row per player per match. Key (match_id, player_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id | VARCHAR | keys; `team_id` HOME or AWAY |
| name, short_name, position | VARCHAR | from `players` |
| shirt_number | INTEGER | |
| minutes_on_pitch | DOUBLE | (`end_ts` - `start_ts`) / 60 |
| tracked_seconds | BIGINT | tracking rows of the player |
| distance_m, distance_km | DOUBLE | sum of `speed_kmh / 3.6` over tracked seconds (0 if none) |
| sprint_seconds, sprint_count | BIGINT | tracked seconds above 25 km/h; sprint efforts |
| max_speed_kmh, avg_speed_kmh | DOUBLE | null if the player has no speed |
| avg_x, avg_y | DOUBLE | mean tracked position (node of the pass network) |
| passes, passes_successful, passes_received | BIGINT | made, successful, received (as `receiver_id`) |
| shots, goals, tackles, fouls, pressures | BIGINT | event counts; a tackle is a duel that directly regains or disrupts the ball; a pressure is any on-ball engagement, tackles and fouls are carved out of that family |

**gold_team_match_stats**: one row per team per match (two per match). Key (match_id, team_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | keys |
| team_name, team_color | VARCHAR | from `matches` (colour may be null or too dark to draw) |
| team_short | VARCHAR | the name fans use (seed `team_names.csv`), else the source short name |
| score, opponent_score | INTEGER | final score from this team's point of view |
| distance_km | DOUBLE | sum of the players |
| sprint_count, sprint_seconds | BIGINT | sums |
| max_speed_kmh | DOUBLE | fastest player |
| passes, passes_successful | BIGINT | sums |
| pass_accuracy | DOUBLE | passes_successful / passes, null if no pass |
| shots, goals, tackles, fouls, pressures | BIGINT | sums |
| avg_x, avg_y | DOUBLE | mean tracked position of the team |

**gold_zone_occupancy**: one row per player per visited zone per match. Key (match_id, player_id, zone_id). Grid of 6 columns x 4
rows over the pitch (cells 17.5 m x 17 m), Silver frame; a zone never visited has no row.

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id | VARCHAR | |
| zone_id | INTEGER | `zone_y * 6 + zone_x`, 0 to 23 |
| zone_x, zone_y | INTEGER | cell column 0 to 5 (toward x = 105), cell row 0 to 3 (toward y = 68). x = 105 and y = 68 stay in the last cell |
| x_min, x_max, y_min, y_max | DOUBLE | bounds of the cell, metres |
| seconds | BIGINT | tracked seconds in the cell |
| share_of_tracked_seconds | DOUBLE | seconds / the player's tracked seconds; the shares of a player add up to 1 (4 decimals) |

**gold_pass_network**: one row per passer and receiver per match, passes with a known receiver only. Key (match_id, passer_id, receiver_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, passer_id, receiver_id, team_id | VARCHAR | passer and receiver are in the same team |
| passer_name, receiver_name | VARCHAR | short names |
| passes, passes_successful | BIGINT | passes from passer to receiver, and the successful ones |
| avg_start_x, avg_start_y, avg_end_x, avg_end_y | DOUBLE | mean start and end of these passes |

**gold_shots**: one row per shot or goal. Key `event_id`.

| Column | Type | Meaning |
|---|---|---|
| match_id, event_id | VARCHAR | |
| ts, period | INTEGER | when |
| player_id, player_name, player_short_name | VARCHAR | the shooter |
| shirt_number | INTEGER | |
| team_id, type | VARCHAR | HOME or AWAY; `shot` or `goal` |
| is_goal | BOOLEAN | `type = 'goal'` |
| x_start, y_start, x_end, y_end | DOUBLE | where the shot was taken and where the action ended (Silver frame, may lie behind the goal line) |
| attacking_goal_x | DOUBLE | 105 for HOME, 0 for AWAY: the goal the team attacks (its centre is y = 34) |
| distance_to_goal_m | DOUBLE | distance from the shot to the centre of that goal |
| score_home_after, score_away_after | INTEGER | running score including this row (ordered by `ts`, `event_id`) |

The source gives no saved / blocked / off-target outcome: there is no expected-goals value.

**gold_player_5min**: one row per player per 5-minute football window per match. Key (match_id, player_id, window_index).

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id | VARCHAR | |
| window_index, period, window_start_ts, window_end_ts | INTEGER | the football window (section 10.2): its first second and the second after its last |
| window_label | VARCHAR | "0-5" ... "45+" ... "90+" |
| window_seconds | BIGINT | length of the window: 300, or the stoppage time for 45+ and 90+ |
| tracked_seconds | BIGINT | tracked seconds in the window (at most window_seconds) |
| coverage | DOUBLE | tracked_seconds / window_seconds: a low value means the window is incomplete |
| distance_m, max_speed_kmh | DOUBLE | distance (0 if none), fastest speed (null if none) |
| sprint_seconds | BIGINT | |
| passes, shots, goals, tackles, fouls, pressures | BIGINT | event counts in the window |

**gold_match_timeline** (F1, F2, F7, E2): one row per team per 5-minute window per match, every window from 0 to
`p2_end_ts`, even if empty: 5-minute football windows (see below). Key (match_id, team_id, window_index).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | |
| window_index, period, window_start_ts, window_end_ts | INTEGER | football window (below); its first second and the second after its last |
| window_label | VARCHAR | "0-5" ... "40-45", "45+", "45-50" ... "85-90", "90+" |
| window_seconds | BIGINT | length of the window: 300, or the stoppage time for 45+ and 90+ |
| passes, final_third_passes | BIGINT | passes of the team; those starting at `x_att >= 70` |
| field_tilt | DOUBLE | final_third_passes / those of both teams in the window; null if neither has one |
| possession_seconds, known_seconds | BIGINT | ball seconds owned by the team; owned by either team |
| possession_share | DOUBLE | possession_seconds / known_seconds, null if 0 |
| possession_greyed | BOOLEAN | `known_seconds < 60`: shown greyed out |
| shots, goals, defensive_actions | BIGINT | `shots` is type `shot` only |
| xthreat_successful_passes | DOUBLE | sum of SkillCorner `xthreat` of successful passes (a pass without a value adds 0) |
| score_home_end, score_away_end | INTEGER | score at the end of the window |

**gold_player_card** (F3, F4, F5, F6, F8): one row per player per match. Key (match_id, player_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id, name, short_name, position, opponent_name | VARCHAR | |
| source_player_id | BIGINT | SkillCorner id: the same player across matches |
| shirt_number | INTEGER | |
| is_outfield, is_eligible | BOOLEAN | eligible = outfield and `tracked_minutes >= 20` |
| tracked_minutes, dpm, top_speed_kmh | DOUBLE | tracking rows / 60; m per minute with a speed; fastest speed whose two positions (this second and the one before) are both detected, shown "about N km/h" (`gold_player_match_stats.max_speed_kmh` keeps all positions) |
| sprint_count, passes_successful, progressive_passes, progressive_passes_successful, defensive_actions, goals, passes_received_successful | BIGINT | |
| sprints_per_min, passes_successful_per_min, progressive_passes_successful_per_min, defensive_actions_per_min | DOUBLE | per tracked minute |
| score_work_rate, score_sprints, score_passing, score_progression, score_defending | INTEGER | `round(100 x percent_rank())` among the eligible players of the match, of dpm and the four rates above; null if not eligible |
| involvement | DOUBLE | (successful passes made + received) / (2 x successful passes of the team) |
| is_hub | BOOLEAN | highest involvement of the team (several only on a tie) |

**gold_team_shape** (C1, C2): one row per team per phase per match. Key (match_id, team_id, phase). Built from
`int_team_shape_second` (team x tracked second, outfield players only).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | |
| phase | VARCHAR | `in_possession`, `out_of_possession` (opponent owns the ball) or `unknown` (nobody, or no ball row) |
| seconds_used | BIGINT | tracked seconds in that phase |
| width, length, area | DOUBLE | means over the seconds of `max(y) - min(y)`, `max(x_att) - min(x_att)` ("outfield block length": SkillCorner's length includes the goalkeeper and is about 21 m longer) and their product, outfield players |
| defensive_line_height | DOUBLE | mean `x_att` of the 4 deepest outfield players (assumes a back four); C2 reads the `out_of_possession` row |
| detected_share | DOUBLE | positions seen by the camera / positions used |

**gold_pressing** (C3): one row per team per 15-minute football window per match (0-15, 15-30, 30-45, 45+, 45-60, 60-75, 75-90, 90+).
Key (match_id, team_id, window_index).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | |
| window_index, period, window_start_ts, window_end_ts, window_label, window_seconds | | the 15-minute football window, as in `gold_match_timeline` |
| defensive_actions, opponent_passes | BIGINT | |
| ppp | DOUBLE | defensive_actions / opponent_passes, null if no opponent pass |
| ppp_greyed | BOOLEAN | `opponent_passes < 10`: too few passes to trust the ratio, greyed out (product.md, C3) |
| defensive_actions_own_third, defensive_actions_middle_third, defensive_actions_final_third | BIGINT | by third of `x_att` at the start |
| high_press_share | DOUBLE | final third / all, null if none |

**gold_team_build_up** (C4, C5): one row per team per match. Key (match_id, team_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | |
| progressive_passes, progressive_passes_successful | BIGINT | |
| tracked_minutes, progressive_passes_per90 | DOUBLE | distinct tracked seconds of the team / 60; progressive_passes / tracked_minutes x 90. No success rate: a failed pass has no reception point, so failed passes rarely look progressive (`product.md`, C4) |
| final_third_entries, entries_left, entries_centre, entries_right | BIGINT | successful passes ending at `x_att >= 70` (those starting there too), by lane of the end |
| share_left, share_centre, share_right | DOUBLE | lane / final_third_entries, null if none |

**gold_player_fatigue** (C6): one row per player per match. Key (match_id, player_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id, short_name, position | VARCHAR | |
| start_ts, end_ts | INTEGER | on the pitch from / to |
| is_outfield, is_eligible | BOOLEAN | eligible = outfield, `minutes_on_pitch >= 30`, `tracked_minutes_first15 >= 5` and `tracked_minutes_last5 >= 2` |
| minutes_on_pitch | DOUBLE | (end_ts - start_ts) / 60 |
| dpm_first15, dpm_last5 | DOUBLE | dpm for `start_ts <= ts < start_ts + 900` and `end_ts - 300 < ts <= end_ts`; null without a speed |
| drop | DOUBLE | `1 - dpm_last5 / dpm_first15`; negative = ran more at the end |
| tracked_minutes_first15, tracked_minutes_last5 | DOUBLE | tracking rows in each window / 60 |

**gold_space_control** (S1): one row per team per 5-minute window with at least one tracked second per match. Key
(match_id, team_id, window_index). Built from `int_space_control_second` (one row per tracked second: share of the 7,140 cells of
a 1 m grid whose nearest player, detected or not, is HOME).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id | VARCHAR | |
| window_index, period, window_start_ts, window_end_ts, window_label, window_seconds | | the 5-minute football window, as in `gold_match_timeline` |
| seconds_used, seconds_in_possession, seconds_out_of_possession, seconds_unknown | BIGINT | tracked seconds, and by owner of the ball |
| space_share, space_share_in_possession, space_share_out_of_possession, space_share_unknown | DOUBLE | mean share of the pitch nearest to the team; HOME + AWAY = 1 |
| detected_share | DOUBLE | positions seen by the camera / positions used |

**gold_team_profile** (C7, F7): one row per team per match. Key (match_id, team_id).

| Column | Type | Meaning |
|---|---|---|
| match_id, team_id, team_name, opponent_name | VARCHAR | |
| possession_share, field_tilt | DOUBLE | whole match, same formulas as the timeline |
| shots_and_goals, progressive_passes | BIGINT | |
| width, length, defensive_line_height | DOUBLE | means over all tracked seconds; the line over the seconds the opponent owns the ball |
| ppp, high_press_share | DOUBLE | whole match |
| progressive_passes_per90, dpm_outfield, share_left, share_centre, share_right | DOUBLE | from `gold_team_build_up`; dpm over outfield rows |
| gap_possession_share, gap_field_tilt, gap_shots_and_goals, gap_progressive_passes, gap_ppp, gap_dpm_outfield | DOUBLE | F7: `(m_team - m_opponent) / ((m_team + m_opponent) / 2)`, null if both are 0; the two teams have opposite gaps |

**gold_match_library** (Match library, Home): one row per stored match. Key `match_id`.

| Column | Type | Meaning |
|---|---|---|
| match_id | VARCHAR | |
| home_team, away_team, home_color, away_color | VARCHAR | from `matches` |
| home_team_short, away_team_short | VARCHAR | the name fans use (dbt seed `team_names.csv`: "Brisbane Roar", not the source's "Brisbane FC"); the source short name for a team not in the seed |
| p1_start_ts, p1_end_ts, p2_start_ts, p2_end_ts | INTEGER | first and last second of each period: the app's football clock restarts the second half at 45:00 from `p2_start_ts` |
| speeds_rejected | BIGINT | player-seconds whose speed Silver rejected (above 40 km/h); shown on the Data quality page |
| home_score, away_score | INTEGER | final score |
| kickoff_utc | VARCHAR | ISO 8601, as in `matches` |
| match_date | DATE | kick-off day (UTC) |
| competition, season, round, stadium | VARCHAR | |
| match_seconds | INTEGER | seconds of the two periods: `(p1_end_ts - p1_start_ts + 1) + (p2_end_ts - p2_start_ts + 1)` |
| tracked_seconds | BIGINT | distinct seconds with tracking |
| tracked_share | DOUBLE | tracked_seconds / match_seconds (m001 0.7358, m002 0.7828) |

**gold_events** (E1, E2): one row per event, runs included. Key `event_id`.

| Column | Type | Meaning |
|---|---|---|
| all columns of `silver.events` | | unchanged (section 9.3) |
| x_att_start, y_att_start, x_att_end, y_att_end | DOUBLE | coordinates seen by the team of the event |
| player_short_name, receiver_short_name | VARCHAR | |
| shirt_number | INTEGER | of the player |
| third, lane | VARCHAR | of the start: `own` / `middle` / `final`, `left` / `centre` / `right`; null without a start |

### 10.4 Known characteristics (measured on 2026-11-16, one replay of each match)

| Item | m001 | m002 | m003 | m004 |
|---|---|---|---|---|
| Match | Brisbane Roar 2-3 Adelaide United | Brisbane Roar 0-1 Perth Glory | Perth Glory 1-3 Brisbane Roar | Sydney FC 4-1 Adelaide United |
| SkillCorner id | 1874553 | 1925299 | 2007448 | 1996435 |
| Rows: player stats / team stats / zones / pass network / shots / 5-minute windows | 32 / 2 / 638 / 261 / 26 / 450 | 32 / 2 / 627 / 258 / 30 / 449 | 29 / 2 / 586 / 225 / 26 / 446 | 30 / 2 / 593 / 236 / 30 / 448 |
| Rows: timeline / cards / shape / pressing / build-up / fatigue / space / profile / events | 40 / 32 / 6 / 16 / 2 / 32 / 40 / 2 / 2,276 | 40 / 32 / 6 / 16 / 2 / 32 / 40 / 2 / 2,376 | 40 / 29 / 6 / 16 / 2 / 29 / 40 / 2 / 2,060 | 40 / 30 / 6 / 16 / 2 / 30 / 40 / 2 / 2,448 |
| Shots table: shots + goals; running score ends | 21 + 5; 2-3 | 29 + 1; 0-1 | 22 + 4; 1-3 | 25 + 5; 4-1 |
| Passes (successful) | 837 (700) | 912 (780) | 752 (632) | 878 (741) |
| Tracked share of the match | 73.6 % | 78.3 % | 76.5 % | 75.6 % |
| Speeds rejected (above 40 km/h, null in Silver) | 0 | 0 | 4 | 0 |
| Possession HOME / AWAY | 39.5 % / 60.5 % | 62.9 % / 37.1 % | 50.0 % / 50.0 % | 52.5 % / 47.5 % |
| Greyed windows: possession (of 20) / pressing (of 16 team rows) | 0 / 2 | 0 / 1 | 1 / 2 | 0 / 2 |
| Eligible player cards / fatigue rows | 26 / 24 of 32 | 27 / 27 of 32 | 22 / 22 of 29 | 22 / 22 of 30 |
| Space control HOME / AWAY | 45.5 % / 54.5 % | 55.8 % / 44.2 % | 48.0 % / 52.0 % | 50.6 % / 49.4 % |
| Width, outfield block length HOME / AWAY (m) | 38.1, 30.2 / 41.7, 32.2 | 39.0, 32.9 / 34.3, 29.2 | 37.4, 30.7 / 37.8, 31.1 | 38.2, 32.7 / 40.0, 33.0 |

Windows: 20 football windows of 5 minutes and 8 of 15 minutes per match (section 10.2). The external check of goal
minutes and possession is in [`requirements-coverage.md`](requirements-coverage.md).

## 11. Quality gates

| Rule | Where | Owner |
|---|---|---|
| Counts after deduplication (events per type), keys, goals = score, detected rows and possession seconds = manifest, frame of events: HOME shots on the right half and AWAY shots on the left half (nothing is written if one fails) | Silver job, before writing (`spark/silver/checks.py`) | Silver |
| Silver contract, keys, 22 players per second, inside the pitch, speed <= 40, event types, orientation of events, consistency | Soda on Silver (`soda/checks/silver.yml`, `make soda-silver`) | Silver / Gold |
| Gold counts, goals, passes and tracked seconds reconciled with Silver | dbt tests (`dbt/tests/assert_*.sql`, run by `make gold`) | Gold |
| Gold contract, ranges, consistency between Gold tables (including: shares add up, greyed flags follow their thresholds, defensive actions never include runs) | Soda on Gold (`soda/checks/gold.yml`, `make soda-gold`) | Gold |
| Last result of the Soda runs | dashboard page "Data quality" (`data/soda/*.json`) | Gold |
