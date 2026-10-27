"""Shared constants and schemas (must match docs/contrat_donnees.md)."""
from pathlib import Path

PITCH_L, PITCH_W = 105.0, 68.0
MATCH_SECONDS = 5400
MAX_SPEED_KMH = 40.0
SPRINT_KMH = 25.0

TRACKING_COLS = ["match_id", "player_id", "ts", "x", "y", "speed_kmh"]
EVENT_COLS = ["match_id", "event_id", "ts", "player_id", "team_id", "type",
              "x_start", "y_start", "x_end", "y_end", "outcome"]
PLAYER_COLS = ["match_id", "player_id", "team_id", "name", "position", "shirt_number"]

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "data" / "generated"
RAW_DIR = ROOT / "data" / "raw" / "skillcorner"
