# Data contract: ingestion phase (source -> Kafka -> bronze)

Owner: ingestion (Kafka, MinIO, bronze). Consumers: Silver (Spark + Iceberg), then Gold and Streamlit.
The code twin of the table sections is `ingestion/schemas.py` (`SCHEMAS`): change both together, by pull request,
and warn the Silver owner. Last update: 2026-11-02. Matches covered: `m001` (SkillCorner 1874553) and `m002` (SkillCorner 1925299).

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
| `player_id` | `H01..H16`, `A01..A16`, ordered by time of entry on the pitch, then shirt number. **Match-local**: `H01` in two matches is two different people |
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

Key: (match_id, player_id, ts). Not every second exists (section 7).

### events: one row = one game action

| Column | Type | Null | Meaning |
|---|---|---|---|
| match_id, event_id | string | no | `event_id` = `<match_id>-e00001`..., numbered after sorting by `ts` |
| ts, period | int32, int8 | no | second of the start of the action |
| player_id, team_id | string | no | player who performs the action, and his team |
| receiver_id | string | yes | for a pass: the teammate it was aimed at; null for other types or if unknown |
| type | string | no | `pass`, `shot`, `goal`, `tackle`, `foul`, `pressure` (no corner in this source). A goal is a `goal`, not a `shot`: shot map = shot + goal |
| x_start, y_start | float64 | yes | where the action starts |
| x_end, y_end | float64 | yes | pass: where the receiver got the ball when known, else the end of the possession; other types: end of the action as given by the source |
| outcome | string | no | text copied from the source: pass outcome (e.g. `successful`), else how the action ended (e.g. `direct_regain`, `foul_committed`, `shot`), `n/a` if none. Profile the real list in Silver |

Derivations: `pass` / `shot` come from `player_possession` rows ending in a pass or a shot; `pressure`, `tackle`, `foul`
from `on_ball_engagement` rows; `goal` = the last shot of a team before its score increases (checked against the real
score for both matches). `off_ball_run` and `passing_option` rows are not kept.

### ball: one row = the ball at one second

`match_id` (string), `ts` (int32), `period` (int8), `x`, `y`, `z` (float64, metres; `z` = height).
Only seconds where the source has a ball position exist.

### players: one row = one player of the match (starters and substitutes who played)

| Column | Type | Meaning |
|---|---|---|
| match_id, player_id, team_id | string | |
| name | string | full name as in the source |
| short_name | string | label form, e.g. `J. Caletti` (some are not shortened by the source) |
| position | string | source acronym of the role played (GK, RCB, AM...) |
| shirt_number | int32 | |
| start_ts, end_ts | int32 | first and last second on the pitch; starters have `start_ts` = 0 |

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

Messages are JSON, one row each, with the column names above. `matches` and `players` are sent at the start of each
replay, then the live tables second by second. Replay speed x1 to x60 (x60: a match lasts about 100 s).

## 6. Bronze (MinIO)

Path: `s3://bronze/<table>/match_id=<id>/ingest_date=<YYYY-MM-DD>/part-<epoch_ms>-<n>.parquet`, with `<table>` in
tracking, events, ball, players, matches. `ingest_date` is the UTC day of writing and exists only in the path.
Columns = the table columns (fixed types) plus `kafka_partition` (int32), `kafka_offset` (int64), `kafka_ts` (int64, ms),
`ingested_at` (int64, ms).

Delivery is at-least-once: a replay, or a consumer restart, adds duplicates. Silver deduplicates on: tracking
(match_id, player_id, ts); events `event_id`; ball (match_id, ts); players (match_id, player_id); matches `match_id`.
Files are micro-batches (about 10 s of arrival, at most 5,000 rows): row order inside and across files is NOT
chronological. Sort by (player_id, ts). `make check MATCH=<id>` compares bronze with the prepared files.

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
| Events | 1,741 | 1,878 |
| By type | pass 837, pressure 835, tackle 36, shot 21, foul 7, goal 5 | pass 912, pressure 890, tackle 35, shot 29, foul 11, goal 1 |
| Goals home-away | 2-3 (= real score) | 0-1 (= real score) |
| Rows outside the pitch | 735 (0.75%) | 618 |
| Rows with null speed | 1,386 | 1,166 |
| Rows above 40 km/h | 0 | 0 |

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