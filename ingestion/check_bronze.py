"""check_bronze.py (step 5): compare the row counts in MinIO bronze with the prepared match.

    python -m ingestion.check_bronze --match m001

OK = same count. MORE = the match was replayed more than once (normal: Silver deduplicates).
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

from ingestion.config import BRONZE_BUCKET, PREPARED_DIR, S3_ENDPOINT, TOPICS


def bronze_rows(s3, table: str, match_id: str) -> int:
    total = 0
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=BRONZE_BUCKET, Prefix=f"{table}/match_id={match_id}/")
    for page in pages:
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=BRONZE_BUCKET, Key=obj["Key"])["Body"].read()
            total += pq.ParquetFile(io.BytesIO(body)).metadata.num_rows
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--match", required=True)
    a = ap.parse_args()
    manifest = json.loads((PREPARED_DIR / a.match / "manifest.json").read_text(encoding="utf-8"))
    expected = {"tracking": manifest["tracking_rows"], "events": manifest["events"],
                "ball": manifest["ball_rows"], "players": manifest["players"], "matches": 1}
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1",
                      aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                      aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"])
    failed = False
    for table, want in expected.items():
        got = bronze_rows(s3, table, a.match)
        if got == want:
            status = "OK"
        elif got > want:
            status = "MORE (replayed? Silver deduplicates)"
        else:
            status = "MISSING"
            failed = True
        print(f"{table:<9} bronze={got:>7} expected={want:>7}  {status}  (topic {TOPICS[table]})")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()