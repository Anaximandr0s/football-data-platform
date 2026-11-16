"""transforms.py: bronze DataFrames -> Silver DataFrames. Pure functions: no reading, no writing.

One match at a time (the job reads one match folder per run), but every function also works on
several matches because all joins and windows use match_id.

Order inside `clean_tracking` follows docs/silver-guide.md section 3:
dedup -> sort -> team -> flip -> clip (+ was_corrected) -> speed / sprint -> gap flag.
"""
from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from spark.silver.config import (
    DECIMALS,
    KAFKA_COLUMNS,
    KEYS,
    MAX_SPEED_KMH,
    PITCH_L,
    PITCH_W,
    RIGHT_TO_LEFT,
    SPRINT_KMH,
)

# ---------------------------------------------------------------- 1. deduplication


def speeds_over_max(bronze_tracking: DataFrame) -> int:
    """Player-seconds of bronze faster than MAX_SPEED_KMH, counted once per key: each replay of a match copies them."""
    return (bronze_tracking.filter(F.col("speed_kmh") > MAX_SPEED_KMH)
            .select(*KEYS["tracking"]).distinct().count())


def dedup(df: DataFrame, keys: list[str]) -> DataFrame:
    """One row per key. Replays and consumer restarts only add copies, so which copy we keep does
    not change the values; we keep the latest written one (ingested_at, then kafka_offset) so the
    result is deterministic. The Kafka metadata columns are dropped afterwards."""
    order = [F.col(c).desc_nulls_last() for c in ("ingested_at", "kafka_offset") if c in df.columns]
    w = Window.partitionBy(*keys).orderBy(*order) if order else Window.partitionBy(*keys).orderBy(*keys)
    out = df.withColumn("_rn", F.row_number().over(w)).filter(F.col("_rn") == 1).drop("_rn")
    return out.drop(*[c for c in KAFKA_COLUMNS if c in out.columns])


# ---------------------------------------------------------------- 4. attack direction


def _needs_flip(period: F.Column, side_p1: F.Column, side_p2: F.Column) -> F.Column:
    """True where HOME attacks toward x = 0 in the row's period (period 0 or unknown: no flip)."""
    return F.coalesce(
        ((period == 1) & (side_p1 == RIGHT_TO_LEFT)) | ((period == 2) & (side_p2 == RIGHT_TO_LEFT)),
        F.lit(False),
    )


def _mirror(df: DataFrame, flip: F.Column, x_cols: list[str], y_cols: list[str]) -> DataFrame:
    """x -> 105 - x and y -> 68 - y where `flip` is true. A null coordinate stays null."""
    d = df.withColumn("_flip", flip)
    for c in x_cols:
        d = d.withColumn(c, F.round(F.when(F.col("_flip"), PITCH_L - F.col(c)).otherwise(F.col(c)), DECIMALS))
    for c in y_cols:
        d = d.withColumn(c, F.round(F.when(F.col("_flip"), PITCH_W - F.col(c)).otherwise(F.col(c)), DECIMALS))
    return d.drop("_flip")


def normalise_direction(df: DataFrame, matches: DataFrame, x_cols: list[str], y_cols: list[str],
                        period_col: str = "period") -> DataFrame:
    """Mirror the pitch in the periods where HOME attacks toward x = 0, so HOME attacks toward x = 105
    in both halves. Applies to every row of the period, both teams. Rows of a match absent from
    `matches` are left as they are."""
    sides = matches.select("match_id", "home_side_p1", "home_side_p2")
    d = df.join(F.broadcast(sides), "match_id", "left")
    flip = _needs_flip(F.col(period_col), F.col("home_side_p1"), F.col("home_side_p2"))
    return _mirror(d, flip, x_cols, y_cols).drop("home_side_p1", "home_side_p2")


# ---------------------------------------------------------------- tables


def clean_players(players: DataFrame) -> DataFrame:
    return dedup(players, KEYS["players"]).orderBy("team_id", "player_id")


def clean_matches(matches: DataFrame) -> DataFrame:
    return dedup(matches, KEYS["matches"]).orderBy("match_id")


def clean_tracking(tracking: DataFrame, players: DataFrame, matches: DataFrame) -> DataFrame:
    """silver.tracking: grain player x second (FOO-03). Columns: match_id, player_id, team_id,
    period, ts, x, y, speed_kmh, speed_rejected, is_sprint, was_corrected, is_after_gap, is_detected.
    `players` and `matches` are the Silver (already deduplicated) tables."""
    t = dedup(tracking, KEYS["tracking"])

    # 3. team: join players on (match_id, player_id). Left join: a missing player shows up as a null
    # team_id (and is reported by the checks) instead of silently losing the row.
    team = players.select("match_id", "player_id", "team_id")
    t = t.join(F.broadcast(team), ["match_id", "player_id"], "left")

    # 5. was_corrected is decided on the position as delivered by bronze. Mirroring the pitch keeps a
    # point inside or outside, so deciding before or after the flip gives the same rows.
    t = t.withColumn(
        "was_corrected",
        (F.col("x") < 0) | (F.col("x") > PITCH_L) | (F.col("y") < 0) | (F.col("y") > PITCH_W),
    )

    # 4. direction, then 5. clip
    t = normalise_direction(t, matches, ["x"], ["y"])
    t = (t.withColumn("x", F.round(F.least(F.greatest(F.col("x"), F.lit(0.0)), F.lit(PITCH_L)), DECIMALS))
          .withColumn("y", F.round(F.least(F.greatest(F.col("y"), F.lit(0.0)), F.lit(PITCH_W)), DECIMALS)))

    # 6. speed: bronze value kept (null stays null, never 0), except above MAX_SPEED_KMH: no player runs that fast,
    # it is a jump from a position SkillCorner estimated (m003: 4 seconds of 43-52 km/h), so it becomes null and adds
    # nothing to a distance. Null never counts as a sprint. Clipping does not recompute the speed: it describes the
    # real movement between two seconds.
    t = t.withColumn("speed_rejected", F.coalesce(F.col("speed_kmh") > MAX_SPEED_KMH, F.lit(False)))
    t = t.withColumn("speed_kmh", F.when(~F.col("speed_rejected"), F.col("speed_kmh")))
    t = t.withColumn("is_sprint", F.coalesce(F.col("speed_kmh") > SPRINT_KMH, F.lit(False)))

    # 2 + 7. order by time per player, flag the first tracked second after a gap. Nothing is invented:
    # the missing seconds stay missing. A player's very first second is NOT "after a gap".
    w = Window.partitionBy("match_id", "player_id").orderBy("ts")
    t = t.withColumn("is_after_gap", F.coalesce(F.col("ts") - F.lag("ts").over(w) > 1, F.lit(False)))

    return (t.withColumn("period", F.col("period").cast("int"))
             .select("match_id", "player_id", "team_id", "period", "ts", "x", "y", "speed_kmh", "speed_rejected",
                     "is_sprint", "was_corrected", "is_after_gap", "is_detected")
             .orderBy("player_id", "ts"))


def clean_ball(ball: DataFrame, matches: DataFrame) -> DataFrame:
    """silver.ball: one row per second with a ball position, direction normalised.
    Not clipped: the ball really leaves the pitch (throw-ins, goal kicks)."""
    b = normalise_direction(dedup(ball, KEYS["ball"]), matches, ["x"], ["y"])
    return (b.withColumn("period", F.col("period").cast("int"))
             .select("match_id", "ts", "period", "x", "y", "z", "possession")
             .orderBy("ts"))


EVENT_DIRECTIONS = ("guide", "per_team")


def clean_events(events: DataFrame, matches: DataFrame, direction: str = "per_team") -> DataFrame:
    """silver.events: one row per game action or off-ball run (type "run"), direction normalised on start and
    end points.
    Not clipped: a shot ending behind the goal line is real information.

    direction="per_team" (default, decided): mirror the AWAY events only, in every period. Measured on
        m001: the source gives event coordinates with the acting team already attacking toward x = 105,
        so this puts events in the same frame as Silver tracking (HOME toward 105, AWAY toward 0).
    direction="guide": the literal rule of docs/silver-guide.md, same as tracking and ball (mirror every
        event of a period where HOME attacks toward x = 0). Kept for comparison; it leaves events
        54 to 58 m away from the player's tracking position in half of the team x period groups."""
    if direction not in EVENT_DIRECTIONS:
        raise ValueError(f"direction must be one of {EVENT_DIRECTIONS}")
    e = dedup(events, KEYS["events"])
    x_cols, y_cols = ["x_start", "x_end"], ["y_start", "y_end"]
    if direction == "guide":
        e = normalise_direction(e, matches, x_cols, y_cols)
    else:
        e = _mirror(e, F.col("team_id") == "AWAY", x_cols, y_cols)
    return (e.withColumn("period", F.col("period").cast("int"))
             .select("match_id", "event_id", "ts", "period", "player_id", "receiver_id", "team_id",
                     "type", "x_start", "y_start", "x_end", "y_end", "outcome", "phase", "phase_against",
                     "xthreat", "dangerous", "speed_band", "subtype", "lead_to_shot", "targeted", "received")
             .orderBy("ts", "event_id"))
