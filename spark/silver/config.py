"""Settings of the Silver job: pitch, business thresholds, deduplication keys, Iceberg and MinIO.

Environment values come from the process or from the `.env` file at the repository root (the same
file the ingestion scripts read). Nothing here touches bronze: bronze is only read.
"""

import os
from pathlib import Path

from ingestion.config import ROOT, S3_ENDPOINT, load_env  # read-only use of the shared settings

load_env()

# --- Football rules ---
PITCH_L, PITCH_W = 105.0, 68.0  # metres, origin bottom-left (ingestion already checked the size)
SPRINT_KMH = 25.0  # is_sprint = speed_kmh > 25
MAX_SPEED_KMH = 40.0  # above: impossible for a player, a jump from an estimated position; set to null
MAX_SPEED_KMH = 40.0  # plausibility limit (the Soda check uses the same value)
RIGHT_TO_LEFT = "right_to_left"  # value of matches.home_side_pN when HOME attacks toward x = 0
DECIMALS = 2  # coordinates keep 2 decimals, like bronze
# How events are oriented: "per_team" = mirror AWAY events only (chosen: the source already gives events with the
# acting team attacking toward x = 105, see spark/silver/README.md decision 1); "guide" = mirror every event like tracking.
EVENTS_DIRECTION = os.getenv("SILVER_EVENTS_DIRECTION", "per_team")

# --- Bronze (input) ---
BRONZE_URI = os.getenv("SILVER_BRONZE_URI", "s3a://bronze")
BRONZE_TABLES = ("tracking", "events", "ball", "players", "matches")
# columns added by bronze_writer; Silver drops them once deduplication is done
KAFKA_COLUMNS = ("kafka_partition", "kafka_offset", "kafka_ts", "ingested_at", "kafka_replay_id")

# Deduplication keys (docs/contrat_donnees.md section 6)
KEYS = {
    "tracking": ["match_id", "player_id", "ts"],
    "events": ["event_id"],
    "ball": ["match_id", "ts"],
    "players": ["match_id", "player_id"],
    "matches": ["match_id"],
}

# --- Silver (output): Iceberg tables <catalog>.<namespace>.<table>, partitioned by match_id ---
CATALOG = os.getenv("SILVER_CATALOG", "lake")
NAMESPACE = os.getenv("SILVER_NAMESPACE", "silver")
WAREHOUSE = os.getenv("SILVER_WAREHOUSE", "s3a://silver/warehouse")

# --- Spark packages (downloaded at the first run). The Iceberg artifact must match the Spark minor
# version of requirements.txt (pyspark 4.0 -> iceberg-spark-runtime-4.0_2.13). Override with
# SPARK_JARS_PACKAGES if you change the Spark version. ---
DEFAULT_PACKAGES = ",".join(
    [
        "org.apache.hadoop:hadoop-aws:3.4.1",
        "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.0",
    ]
)
PACKAGES = os.getenv("SPARK_JARS_PACKAGES", DEFAULT_PACKAGES)

# Where the ingestion manifests are (only used to compare the counts, optional)
MANIFEST_DIR = ROOT / "data" / "prepared"
QUALITY_DIR = Path(os.getenv("QUALITY_OUT_DIR", ROOT / "data" / "quality"))  # silver_<match>.json per run

# --- MinIO ---
S3_ENDPOINT_URL = S3_ENDPOINT  # http://localhost:9000, or http://minio:9000 inside Docker (MINIO_ENDPOINT)
S3_USER = os.getenv("MINIO_ROOT_USER", "")
S3_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD", "")
