"""live_stats.py: Spark Structured Streaming job of FOO-08. Reads the replay topics, computes per football window the
live stats of docs/product.md (F2 possession, F4 distance and F5 top speed per player, C3 pressing) with the formulas
of Gold, and writes them to the compacted Kafka topic foot-live-stats, which the Live page reads.

    make streaming          (docker: submits to spark://spark-master:7077, runs until stopped)

How it keeps the numbers right:
  replays      every message carries the Kafka header replay_id (producer_foot); all groups include it
  windows      football windows from clock.window_index (app/streamlit/clock.py, shipped with --py-files), with the
               period bounds of the replay's foot-matches message, not Spark's time windows
  formulas     a speed above 40 km/h counts as null (Silver's rule), a repeated message counts once (dedup within a
               10-minute watermark of the Kafka time), runs are not actions, thirds by the event's x (the source gives
               events in the attacking frame of the acting team, which is Gold's x_att)
  output       rows.py: one row = the full current value of a window, never an increment, sent again when it changes
               or becomes complete (end + 10 s of tracking, or the last second of the match)
  restarts     the aggregation state and the Kafka offsets live in the checkpoint (CHECKPOINT, MinIO); a batch replayed
               after a crash sends the same full rows again, which the compacted topic overwrites
"""
import json
import os
import time

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType

import clock
from spark.streaming import progress, rows

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = {t: os.getenv(f"KAFKA_TOPIC_{t.upper()}", f"foot-{t}") for t in ("tracking", "events", "ball", "players",
                                                                            "matches")}
OUT_TOPIC = os.getenv("KAFKA_TOPIC_LIVE_STATS", "foot-live-stats")
CHECKPOINT = os.getenv("STREAMING_CHECKPOINT", "s3a://checkpoints/streaming-5min")
TRIGGER = os.getenv("STREAMING_TRIGGER", "5 seconds")
MAX_SPEED_KMH = 40.0       # Silver's rule (spark/silver/config.py)

SCHEMA = {
    "tracking": "match_id string, player_id string, ts int, period int, x double, y double, speed_kmh double",
    "ball": "match_id string, ts int, period int, possession string",
    "events": "match_id string, event_id string, ts int, period int, team_id string, type string, x_start double",
    "matches": "match_id string, p1_start_ts int, p1_end_ts int, p2_start_ts int, p2_end_ts int",
    "players": "match_id string, player_id string, team_id string",
}
def replay_id():
    """The replay_id Kafka header as a column (a function: a column needs the SparkSession, built in main)."""
    return F.expr("cast(filter(headers, h -> h.key = 'replay_id')[0].value as string)")
BOUNDS = ["p1_start_ts", "p1_end_ts", "p2_start_ts", "p2_end_ts"]


def window_udf(size: int):
    return F.udf(lambda ts, period, p1, p2: clock.window_index(ts, period, p1, p2, size), IntegerType())


def stream(spark: SparkSession, table: str) -> DataFrame:
    """One replay topic as a stream: the parsed message, its replay_id and its Kafka time."""
    raw = (spark.readStream.format("kafka").option("kafka.bootstrap.servers", BOOTSTRAP)
           .option("subscribe", TOPIC[table]).option("includeHeaders", "true")
           .option("startingOffsets", "latest").option("failOnDataLoss", "false").load())
    return (raw.select(replay_id().alias("replay_id"), F.col("timestamp").alias("kafka_time"),
                       F.from_json(F.col("value").cast("string"), SCHEMA[table]).alias("m"))
            .where(F.col("replay_id").isNotNull()).select("replay_id", "kafka_time", "m.*"))


def static(spark: SparkSession, table: str) -> DataFrame:
    """A small reference topic (matches, players) read as a table; re-read at every micro-batch of the join, so a new
    replay is known as soon as its first messages arrive."""
    raw = (spark.read.format("kafka").option("kafka.bootstrap.servers", BOOTSTRAP)
           .option("subscribe", TOPIC[table]).option("includeHeaders", "true")
           .option("startingOffsets", "earliest").option("endingOffsets", "latest").load())
    return (raw.select(replay_id().alias("replay_id"), F.from_json(F.col("value").cast("string"), SCHEMA[table]).alias("m"))
            .where(F.col("replay_id").isNotNull()).select("replay_id", "m.*").dropDuplicates(["replay_id", "match_id"]
                                                                                              if table == "matches"
                                                                                              else ["replay_id",
                                                                                                    "player_id"]))


def once(df: DataFrame, keys: list[str]) -> DataFrame:
    """A repeated message counts once (at-least-once delivery), within 10 minutes of Kafka time."""
    return df.withWatermark("kafka_time", "10 minutes").dropDuplicatesWithinWatermark(keys)


def with_window(df: DataFrame, matches: DataFrame, size: int) -> DataFrame:
    return (df.join(matches.drop("match_id"), "replay_id")
            .withColumn("window_index", window_udf(size)("ts", "period", "p1_start_ts", "p2_start_ts")))


def player_counts(spark: SparkSession, matches: DataFrame) -> DataFrame:
    trk = once(stream(spark, "tracking"), ["replay_id", "player_id", "ts"])
    speed = F.when(F.col("speed_kmh") <= MAX_SPEED_KMH, F.col("speed_kmh"))     # above 40: null, as Silver
    players = static(spark, "players").drop("match_id")
    return (with_window(trk, matches, 300).join(players, ["replay_id", "player_id"], "left")
            .groupBy("replay_id", "match_id", "player_id", "team_id", "window_index", *BOUNDS)
            .agg(F.count(F.lit(1)).alias("tracked_seconds"), F.sum(speed / 3.6).alias("distance_m"),
                 F.count(F.when(speed > 25, 1)).alias("sprint_seconds"), F.max(speed).alias("max_speed_kmh"),
                 F.max("ts").alias("last_ts")))


def team_counts(spark: SparkSession, matches: DataFrame, size: int) -> DataFrame:
    """Ball (possession) and events (passes, defensive actions) of both teams per window, in one aggregation."""
    ball = once(stream(spark, "ball"), ["replay_id", "ts"]).select(
        "replay_id", "kafka_time", "match_id", "ts", "period", "possession",
        F.lit(None).cast("string").alias("team_id"), F.lit(None).cast("string").alias("type"),
        F.lit(None).cast("double").alias("x_start"))
    ev = once(stream(spark, "events"), ["replay_id", "event_id"]).select(
        "replay_id", "kafka_time", "match_id", "ts", "period", F.lit(None).cast("string").alias("possession"),
        "team_id", "type", "x_start")
    d = with_window(ball.unionByName(ev), matches, size)
    defensive = F.col("type").isin("pressure", "tackle", "foul")
    aggs = [F.max("ts").alias("last_ts")]
    for team in ("HOME", "AWAY"):
        t = team.lower()
        mine = F.col("team_id") == team
        aggs += [F.count(F.when(F.col("possession") == team, 1)).alias(f"{t}_possession"),
                 F.count(F.when(mine & (F.col("type") == "pass"), 1)).alias(f"{t}_passes"),
                 F.count(F.when(mine & defensive, 1)).alias(f"{t}_da"),
                 F.count(F.when(mine & defensive & (F.col("x_start") < 35), 1)).alias(f"{t}_da_own"),
                 F.count(F.when(mine & defensive & (F.col("x_start") >= 35) & (F.col("x_start") < 70), 1))
                 .alias(f"{t}_da_middle"),
                 F.count(F.when(mine & defensive & (F.col("x_start") >= 70), 1)).alias(f"{t}_da_final")]
    return d.groupBy("replay_id", "match_id", "window_index", *BOUNDS).agg(*aggs)


def stored_rows(spark: SparkSession, kinds: set[str]) -> dict[str, dict]:
    """The latest row per key already in foot-live-stats: after a restart, completion goes on from there."""
    raw = (spark.read.format("kafka").option("kafka.bootstrap.servers", BOOTSTRAP).option("subscribe", OUT_TOPIC)
           .option("startingOffsets", "earliest").option("endingOffsets", "latest").load())
    latest: dict[str, dict] = {}
    for r in raw.select(F.col("key").cast("string").alias("k"), F.col("value").cast("string").alias("v"),
                        "offset", "partition").orderBy("partition", "offset").collect():
        row = json.loads(r.v)
        if row.get("kind") in kinds:
            latest[r.k] = row
    return latest


def sink(spark: SparkSession, build, kinds: set[str]):
    """foreachBatch: the updated windows of the batch -> full rows -> foot-live-stats (with the completed ones)."""
    store = stored_rows(spark, kinds)

    def write(batch: DataFrame, _batch_id: int) -> None:
        updated = [r for agg in batch.collect() for r in build(agg.asDict())]
        out = rows.merge(store, updated, int(time.time() * 1000))
        if out:
            spark.createDataFrame([(rows.key(r), json.dumps(r)) for r in out], "key string, value string") \
                .write.format("kafka").option("kafka.bootstrap.servers", BOOTSTRAP).option("topic", OUT_TOPIC).save()
    return write


def main() -> None:
    spark = (SparkSession.builder.appName("streaming-5min")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.sql.shuffle.partitions", "4")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    spark.streams.addListener(progress.ProgressFile())
    matches = static(spark, "matches")
    queries = [
        ("players-5min", player_counts(spark, matches), lambda a: [rows.player_5min(a)], {"player"}),
        ("teams-5min", team_counts(spark, matches, 300), rows.team_5min, {"team"}),
        ("pressing-15min", team_counts(spark, matches, 900), rows.team_15min, {"pressing"}),
    ]
    for name, df, build, kinds in queries:
        (df.writeStream.queryName(name).outputMode("update").trigger(processingTime=TRIGGER)
         .option("checkpointLocation", f"{CHECKPOINT}/{name}")
         .foreachBatch(sink(spark, build, kinds)).start())
    print(f"streaming to {OUT_TOPIC}, checkpoints in {CHECKPOINT}", flush=True)
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
