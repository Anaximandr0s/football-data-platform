"""Download SkillCorner open-data files for one match (MIT licence, credit SkillCorner).

  python scripts/download_skillcorner.py 1925299

Tracking files are stored with Git LFS (~100 MB each), so they come from
media.githubusercontent.com, not raw.githubusercontent.com. Files go to data/raw/skillcorner/<id>/
(git-ignored: never commit them).
"""
import sys
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches/{i}/{i}_{f}"
LFS = "https://media.githubusercontent.com/media/SkillCorner/opendata/master/data/matches/{i}/{i}_{f}"
FILES = [("match.json", RAW), ("dynamic_events.csv", RAW), ("tracking_extrapolated.jsonl", LFS)]
DEST = Path(__file__).resolve().parents[1] / "data" / "raw" / "skillcorner"


def main(ids: list[str]) -> None:
    for i in ids:
        out = DEST / i
        out.mkdir(parents=True, exist_ok=True)
        for name, tpl in FILES:
            target = out / f"{i}_{name}"
            if target.exists() and target.stat().st_size > 1000:
                print("skip (exists)", target.name)
                continue
            print("downloading", target.name, flush=True)
            urllib.request.urlretrieve(tpl.format(i=i, f=name), target)
            with open(target, "rb") as fh:
                if fh.read(40).startswith(b"version https://git-lfs"):
                    target.unlink()
                    sys.exit(f"{name} is a Git LFS pointer, not data. Use the media.githubusercontent.com URL.")
        print("ok:", out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
