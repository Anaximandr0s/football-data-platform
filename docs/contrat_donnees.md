# Data contract (A ⇄ B). Change only via PR, warn the other person.

## Global conventions
- Pitch: 105 × 68 m, origin bottom-left, `x ∈ [0,105]`, `y ∈ [0,68]`, metres.
- `ts`: integer seconds since kick-off (0 … 5399). `ts_utc`: timestamp.
- `team_id` ∈ {`HOME`, `AWAY`}. `player_id`: `H01..H11`, `A01..A11`. `match_id`: `m001`.
- Event types: `pass, shot, goal, tackle, foul, corner` (+ `pressure`, only present in real matches). A goal is an event of type `goal`, not `shot`: shots map = shot + goal.
- Player ids: simulated match `H01..H11`/`A01..A11`; real match up to `H16`/`A16` (substitutes). Names are always fictional.
- Bronze is written by `kafka/bronze_writer.py` as Parquet: `s3://bronze/<tracking|events>/match_id=<id>/part-*.parquet` with extra columns `kafka_partition, kafka_offset, kafka_ts, ingested_at`. Delivery is at-least-once: **Silver deduplicates**.

## Kafka
| Topic | Key | Partitions |
|---|---|---|
| `foot-tracking` | `player_id` | 3 |
| `foot-events` | `match_id` | 1 |

## Tables
| Table | Grain | Columns |
|---|---|---|
| `bronze.tracking` | raw message | `match_id, player_id, ts, x, y, speed_kmh` (as received) |
| `bronze.events` | raw message | as received |
| `silver.tracking` | player × second | `match_id, player_id, team_id, ts, x, y, speed_kmh, is_sprint, was_corrected` |
| `silver.events` | one action | `match_id, event_id, ts, player_id, team_id, type, x_start, y_start, x_end, y_end, outcome` |
| `silver.players` | player × match | `match_id, player_id, team_id, name, position, shirt_number` |

## Gold tables (grain documented in dbt `schema.yml`)
| Table | Grain |
|---|---|
| `gold_player_match_stats` | player × match |
| `gold_team_match_stats` | team × match |
| `gold_zone_occupancy` | player × pitch zone |
| `gold_pass_network` | passer × receiver × match |
| `gold_shots` | one shot |
| `gold_player_5min` | player × 5-min window |

## Sample data
Person A pushes small Parquet files in `data/sample/` matching these schemas so B is never blocked.
