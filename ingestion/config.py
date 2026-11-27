"""Settings shared by every ingestion script: paths, constants, Kafka topics, MinIO.

Values come from the environment. A `.env` file at the repository root is read automatically.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "skillcorner"   # downloaded files (git-ignored)
PREPARED_DIR = ROOT / "data" / "prepared"          # output of ingest_foot (git-ignored)


def load_env() -> None:
    """Read ROOT/.env into os.environ (variables already set win)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+#.*$", "", line.strip())
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

# --- Football ---
PITCH_L, PITCH_W = 105.0, 68.0
FPS = 10  # SkillCorner tracking frequency; we keep 1 frame out of FPS (= 1 Hz)

# --- Kafka ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:29092")

# table -> Kafka topic
TOPICS = {
    "tracking": os.getenv("KAFKA_TOPIC_TRACKING", "foot-tracking"),
    "events": os.getenv("KAFKA_TOPIC_EVENTS", "foot-events"),
    "ball": os.getenv("KAFKA_TOPIC_BALL", "foot-ball"),
    "players": os.getenv("KAFKA_TOPIC_PLAYERS", "foot-players"),
    "matches": os.getenv("KAFKA_TOPIC_MATCHES", "foot-matches"),
}
# table -> message key (all rows of one player share a partition, so their order is kept)
# Kafka header carried by every message of one replay: "<match_id>-<UTC start, YYYYMMDDTHHMMSSZ>"
REPLAY_HEADER = "replay_id"
KEYS = {"tracking": "player_id", "events": "match_id", "ball": "match_id",
        "players": "player_id", "matches": "match_id"}

# --- MinIO (S3 API) ---
S3_ENDPOINT = os.getenv("MINIO_ENDPOINT", f"http://localhost:{os.getenv('MINIO_API_PORT', '9000')}")
BRONZE_BUCKET = os.getenv("MINIO_BUCKET_BRONZE", "bronze")