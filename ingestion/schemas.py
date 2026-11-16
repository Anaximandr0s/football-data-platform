"""The data contract in code: the schema of every table (Parquet files, Kafka messages, bronze).

docs/contrat_donnees.md documents these tables.
"""
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

S, I32, I64, I8, F, B = pa.string(), pa.int32(), pa.int64(), pa.int8(), pa.float64(), pa.bool_()
SCHEMAS = {
    # one row = one player at one second (players on the pitch only)
    "tracking": pa.schema([("match_id", S), ("player_id", S), ("ts", I32), ("period", I8),
                           ("x", F), ("y", F), ("speed_kmh", F), ("is_detected", B)]),
    # one row = one game action, or one off-ball run (type "run")
    "events": pa.schema([("match_id", S), ("event_id", S), ("ts", I32), ("period", I8),
                         ("player_id", S), ("receiver_id", S), ("team_id", S), ("type", S),
                         ("x_start", F), ("y_start", F), ("x_end", F), ("y_end", F),
                         ("outcome", S), ("phase", S), ("phase_against", S), ("xthreat", F),
                         ("dangerous", B), ("speed_band", S), ("subtype", S), ("lead_to_shot", B),
                         ("targeted", B), ("received", B)]),
    # one row = the ball at one second
    "ball": pa.schema([("match_id", S), ("ts", I32), ("period", I8),
                       ("x", F), ("y", F), ("z", F), ("possession", S)]),
    # one row = one player of the match (starters and substitutes who played)
    "players": pa.schema([("match_id", S), ("player_id", S), ("team_id", S),
                          ("name", S), ("short_name", S), ("position", S), ("shirt_number", I32),
                          ("start_ts", I32), ("end_ts", I32), ("source_player_id", I64)]),
    # one row = one match
    "matches": pa.schema([("match_id", S), ("competition", S), ("season", S), ("round", S),
                          ("kickoff_utc", S), ("stadium", S),
                          ("home_team", S), ("away_team", S),
                          ("home_team_short", S), ("away_team_short", S),
                          ("home_color", S), ("away_color", S),
                          ("home_score", I32), ("away_score", I32),
                          ("pitch_length", F), ("pitch_width", F),
                          ("p1_start_ts", I32), ("p1_end_ts", I32),
                          ("p2_start_ts", I32), ("p2_end_ts", I32),
                          ("home_side_p1", S), ("home_side_p2", S)]),
}

KAFKA_FIELDS = [("kafka_partition", pa.int32()), ("kafka_offset", pa.int64()),
                ("kafka_ts", pa.int64()), ("ingested_at", pa.int64()),
                ("kafka_replay_id", pa.string())]   # the replay_id header; null for messages sent before it existed


def bronze_schema(table: str) -> pa.Schema:
    """Table schema + the Kafka metadata columns added by bronze_writer."""
    return pa.schema(list(SCHEMAS[table]) + [pa.field(n, t) for n, t in KAFKA_FIELDS])


def write_parquet(df, table: str, path: Path) -> None:
    """Write a DataFrame with exactly the columns and types of the table's schema."""
    schema = SCHEMAS[table]
    cols = [f.name for f in schema]
    pq.write_table(pa.Table.from_pandas(df[cols], schema=schema, preserve_index=False), path)