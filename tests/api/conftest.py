"""The Control Center imports the app's clock and quality code, as in its container (PYTHONPATH)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "app" / "api"), str(ROOT / "app" / "streamlit"), str(ROOT / "scripts"), str(ROOT)]
