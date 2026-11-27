"""control_center_thumbnails.py: the "what you see" pictures of the Control Center's diagram, taken from the real pages
(app/api/static/thumbs/*.png, 800 x 448). Run it again after a page changes.

    pip install playwright && playwright install chromium     # once: a browser for the screenshots (dev tool only)
    python scripts/control_center_thumbnails.py

Needs `make demo` running. For the live pitch it starts a replay through the Control Center, 30 s before the first goal
(a partial replay: live only, no Dagster run), and stops it. Grafana's login is read from its container's environment
(set from .env) and never printed."""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "api" / "static" / "thumbs"
CONTROL = os.getenv("CONTROL_URL", "http://localhost:8000")
APP = os.getenv("APP_URL_PUBLIC", "http://localhost:8501")
GRAFANA = os.getenv("GRAFANA_URL_PUBLIC", "http://localhost:3001")
DAGSTER = os.getenv("DAGSTER_URL_PUBLIC", "http://localhost:3000")
MATCH = os.getenv("THUMB_MATCH", "m003")
VIEW = {"width": 1600, "height": 896}  # 16:9, shrunk to 800 x 448


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{CONTROL}{path}", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def save(target, name: str) -> None:
    """target: a page, or one element of it (scrolled into view, taken whole)."""
    raw = OUT / f"{name}.raw.png"
    target.screenshot(path=raw)
    shot = Image.open(raw).convert("RGB")
    shot.thumbnail((800, 448), Image.LANCZOS)  # keeps its proportions (a pitch is not 16:9)
    frame = Image.new("RGB", (800, 448), "white")
    frame.paste(shot, ((800 - shot.width) // 2, (448 - shot.height) // 2))
    frame.save(OUT / f"{name}.png", optimize=True)
    raw.unlink()
    print(f"{name}.png")


def settle(page, selector: str, seconds: float = 8) -> None:
    page.wait_for_selector(selector, timeout=120_000)
    time.sleep(seconds)


def grafana_login(page) -> None:
    env = dict(
        line.split("=", 1)
        for line in subprocess.run(
            ["docker", "exec", "football-platform-grafana-1", "env"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
        if "=" in line
    )
    page.goto(f"{GRAFANA}/login")
    page.fill("input[name=user]", env["GF_SECURITY_ADMIN_USER"])
    page.fill("input[name=password]", env["GF_SECURITY_ADMIN_PASSWORD"])
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=30_000)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEW)
        post("/api/replay/start", {"match": MATCH, "speed": 1, "start": "goal"})
        try:
            time.sleep(20)
            page.goto(f"{APP}/live_match?match={MATCH}", wait_until="commit", timeout=120_000)
            settle(page, "text=NOW PLAYING", 10)
            canvases = page.locator(
                "[data-testid='stMain'] canvas"
            )  # tables are canvases too: the pitch is the largest
            areas = [
                (b["width"] * b["height"], i) for i in range(canvases.count()) if (b := canvases.nth(i).bounding_box())
            ]
            save(canvases.nth(max(areas)[1]), "live")
        finally:
            post("/api/replay/stop", {"match": MATCH})
        for name, url in (
            ("fan", f"{APP}/match_story?view=fan&match={MATCH}"),
            ("coach", f"{APP}/team_analysis?view=coach&match={MATCH}"),
        ):
            page.goto(url, wait_until="commit", timeout=120_000)
            settle(page, "[data-testid='stMain'] h1")
            save(page, name)
        grafana_login(page)
        page.goto(f"{GRAFANA}/d/slo?orgId=1&kiosk&from=now-7d&to=now")
        settle(page, ".react-grid-layout", 10)
        save(page, "grafana")
        page.goto(f"{DAGSTER}/asset-groups")
        settle(page, "body", 12)
        save(page, "dagster")
        browser.close()


if __name__ == "__main__":
    main()
