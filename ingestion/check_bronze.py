"""check_bronze.py (step 5): compare the row counts in MinIO bronze with the prepared match.

    python -m ingestion.check_bronze --match m001 [--replay m001-20261117T120000Z]

Counts one replay (its folder replay_id=<replay>): the one given, else the newest of the match.
OK = same count. MORE = some messages were delivered twice (normal: at-least-once; Silver deduplicates).
MISSING = rows are not in bronze yet (is bronze_writer running? did the replay finish?).
Exit code 1 if any table is MISSING.
"""

import argparse
import io
import json
import os
import sys

import boto3
import pyarrow.parquet as pq

from ingestion import replay_ids
from ingestion.config import BRONZE_BUCKET, PREPARED_DIR, S3_ENDPOINT, TOPICS


def replays(s3, match_id: str) -> list[str]:
    """The replay folders of the match (its matches table), oldest first: a replay id ends with its start time."""
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=BRONZE_BUCKET, Prefix=f"matches/match_id={match_id}/replay_id=", Delimiter="/"
    )
    names = [
        p["Prefix"].rstrip("/").split("replay_id=", 1)[1] for page in pages for p in page.get("CommonPrefixes", [])
    ]
    return sorted(n for n in names if n != "none" and not replay_ids.is_partial(n))


def bronze_rows(s3, table: str, match_id: str, replay_id: str) -> int:
    total = 0
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=BRONZE_BUCKET, Prefix=f"{table}/match_id={match_id}/replay_id={replay_id}/"
    )
    for page in pages:
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=BRONZE_BUCKET, Key=obj["Key"])["Body"].read()
            total += pq.ParquetFile(io.BytesIO(body)).metadata.num_rows
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", required=True)
    ap.add_argument("--replay", help="the replay to count; default: the newest of the match")
    a = ap.parse_args()
    manifest = json.loads((PREPARED_DIR / a.match / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "tracking": manifest["tracking_rows"],
        "events": manifest["events"],
        "ball": manifest["ball_rows"],
        "players": manifest["players"],
        "matches": 1,
    }
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
    )
    if a.replay and replay_ids.is_partial(a.replay):
        sys.exit(f"{a.replay} started after kick-off: a partial replay is never a whole match in Bronze")
    replay = a.replay or next(iter(reversed(replays(s3, a.match))), None)
    if replay is None:
        sys.exit(f"{a.match}: no replay folder in bronze: replay the match (make replay MATCH={a.match})")
    print(f"replay {replay}")
    failed = False
    for table, want in expected.items():
        got = bronze_rows(s3, table, a.match, replay)
        if got == want:
            status = "OK"
        elif got > want:
            status = "MORE (delivered twice; Silver deduplicates)"
        else:
            status = "MISSING"
            failed = True
        print(f"{table:<9} bronze={got:>7} expected={want:>7}  {status}  (topic {TOPICS[table]})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
