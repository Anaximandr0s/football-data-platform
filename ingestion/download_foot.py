"""download_foot.py (step 1): download SkillCorner open-data matches into data/raw/skillcorner/<id>/.

    python -m ingestion.download_foot 1874553              # one or more explicit ids
    python -m ingestion.download_foot --list               # ids available in the repository
    python -m ingestion.download_foot --random 2 --seed 7  # explore: pick 2 at random

Data: SkillCorner open data (MIT licence).
Pin the ids you really use (a random pick differs from one machine to another).
Tracking files are Git LFS (~100 MB), so they come from media.githubusercontent.com.
"""

import argparse
import json
import os
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ingestion.config import RAW_DIR

REPO = os.getenv("SKILLCORNER_REPO", "SkillCorner/opendata")
BRANCH = os.getenv("SKILLCORNER_BRANCH", "master")
RAW = "https://raw.githubusercontent.com/{repo}/{branch}/data/{path}"
LFS = "https://media.githubusercontent.com/media/{repo}/{branch}/data/{path}"
FILES = [("match.json", RAW), ("dynamic_events.csv", RAW), ("tracking_extrapolated.jsonl", LFS)]


def available_ids() -> list[int]:
    url = RAW.format(repo=REPO, branch=BRANCH, path="matches.json")
    with urllib.request.urlopen(url, timeout=30) as resp:
        return sorted(int(m["id"]) for m in json.load(resp))


def fetch(url: str, target: Path) -> None:
    """Download to <file>.part, check it is real data, then rename (no half files)."""
    part = target.with_name(target.name + ".part")
    try:
        urllib.request.urlretrieve(url, part)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} for {url}")
    with open(part, "rb") as fh:
        if fh.read(40).startswith(b"version https://git-lfs"):
            part.unlink()
            sys.exit(f"{target.name} is a Git LFS pointer, not data. Check SKILLCORNER_REPO/BRANCH.")
    part.replace(target)


def download(match_id: int) -> None:
    out = RAW_DIR / str(match_id)
    out.mkdir(parents=True, exist_ok=True)
    for name, tpl in FILES:
        target = out / f"{match_id}_{name}"
        if target.exists():
            print("skip (exists)", target.name)
            continue
        print("downloading", target.name, flush=True)
        fetch(tpl.format(repo=REPO, branch=BRANCH, path=f"matches/{match_id}/{match_id}_{name}"), target)
    print("ok:", out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("ids", nargs="*", type=int, help="SkillCorner match ids")
    ap.add_argument("--list", action="store_true", help="print the available match ids and exit")
    ap.add_argument("--random", type=int, metavar="N", help="pick N matches at random")
    ap.add_argument("--seed", type=int, help="seed for --random (reproducible pick)")
    a = ap.parse_args()

    if a.list:
        print(*available_ids(), sep="\n")
        return
    ids = list(a.ids)
    if a.random:
        ids += random.Random(a.seed).sample(available_ids(), a.random)
    if not ids:
        ap.error("give at least one match id, or use --random N / --list")
    for i in ids:
        download(i)
    print("downloaded ids:", *ids)


if __name__ == "__main__":
    main()
