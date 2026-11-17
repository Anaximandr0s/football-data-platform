"""The exporter imports quality.py from the app, as it does in its container (PYTHONPATH)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "monitoring" / "exporter"), str(ROOT / "app" / "streamlit")]
