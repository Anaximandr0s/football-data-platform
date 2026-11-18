"""bronze_prune.py (`make bronze-prune KEEP=3`): Bronze keeps every replay; this keeps, per match, the last KEEP
complete replays and every newer one (a replay may still be running), and deletes the older replay folders, the
replay_id=none folder and the files written before Bronze had one folder per replay.

    python scripts/bronze_prune.py --keep 3            # show what would be deleted, and the space it frees
    python scripts/bronze_prune.py --keep 3 --delete   # delete it

A replay is complete when its tracking reaches the match's last second (matches.p2_end_ts), the rule Silver uses.
Silver only ever reads the latest complete replay, so nothing it reads is deleted. Run from the repository root."""
import argparse
import io
import os
import sys
from collections import defaultdict
from pathlib import Path

import boto3
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingestion import replay_ids  # noqa: E402
from ingestion.config import BRONZE_BUCKET, S3_ENDPOINT, TOPICS  # noqa: E402


def parse(key: str) -> tuple[str, str, str | None] | None:
    """(table, match_id, replay_id or None for the old layout) of a Bronze object key."""
    parts = key.split("/")
    if len(parts) < 3 or not parts[1].startswith("match_id="):
        return None
    replay = parts[2].split("=", 1)[1] if parts[2].startswith("replay_id=") else None
    return parts[0], parts[1].split("=", 1)[1], replay


def plan(objects: dict[str, int], is_complete, keep: int) -> dict[str, list[str]]:
    """objects: key -> size. Returns {"keep": [...], "delete": [...]} keys. Per match, replays are walked newest first
    (a replay id ends with its start time); everything after the keep-th complete one is deleted, with the old layout
    and replay_id=none."""
    by_match: dict[str, set[str]] = defaultdict(set)
    for key in objects:
        p = parse(key)
        if p and p[2] and p[2] != "none":
            by_match[p[1]].add(p[2])
    kept: dict[str, set[str]] = {}
    for match, replays in by_match.items():
        out, complete = set(), 0
        for r in sorted(replays, reverse=True):
            if complete >= keep:
                break
            out.add(r)
            complete += bool(is_complete(match, r))
        kept[match] = out
    result = {"keep": [], "delete": []}
    for key in sorted(objects):
        p = parse(key)
        stays = p is None or (p[2] not in (None, "none") and p[2] in kept.get(p[1], set()))
        result["keep" if stays else "delete"].append(key)
    return result


def complete_fn(s3, objects: dict[str, int]):
    """Reads only what is needed: the matches row of the replay, and the max ts in each tracking file's footer."""
    cache: dict[tuple[str, str], bool] = {}

    def body(key: str) -> bytes:
        return s3.get_object(Bucket=BRONZE_BUCKET, Key=key)["Body"].read()

    def is_complete(match: str, replay: str) -> bool:
        if replay_ids.is_partial(replay):          # started after kick-off: never a whole match
            return False
        if (match, replay) not in cache:
            prefix = f"/match_id={match}/replay_id={replay}/"
            matches = [k for k in objects if k.startswith("matches" + prefix)]
            tracking = [k for k in objects if k.startswith("tracking" + prefix)]
            end = max((pq.read_table(io.BytesIO(body(k)), columns=["p2_end_ts"]).column(0).to_pylist()[0]
                       for k in matches), default=None)
            last = None
            for k in tracking:
                meta = pq.ParquetFile(io.BytesIO(body(k))).metadata
                col = meta.schema.names.index("ts")
                for g in range(meta.num_row_groups):
                    stats = meta.row_group(g).column(col).statistics
                    if stats is not None and stats.has_min_max:
                        last = stats.max if last is None else max(last, stats.max)
            cache[(match, replay)] = end is not None and last is not None and last >= end
        return cache[(match, replay)]
    return is_complete


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--keep", type=int, default=3, help="complete replays kept per match (default 3)")
    ap.add_argument("--delete", action="store_true", help="delete (without it: only show what would be deleted)")
    a = ap.parse_args()
    if a.keep < 1:
        ap.error("--keep must be at least 1: Silver needs the latest complete replay")
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT, region_name="us-east-1",
                      aws_access_key_id=os.environ["MINIO_ROOT_USER"],
                      aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"])
    objects = {}
    for table in TOPICS:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BRONZE_BUCKET, Prefix=f"{table}/"):
            objects.update({o["Key"]: o["Size"] for o in page.get("Contents", [])})
    result = plan(objects, complete_fn(s3, objects), a.keep)
    groups: dict[tuple, list[int]] = defaultdict(list)
    for key in result["delete"]:
        table, match, replay = parse(key) or (key.split("/")[0], "?", None)
        groups[(match, replay or "old layout (no replay folder)")].append(objects[key])
    for (match, replay), sizes in sorted(groups.items()):
        print(f"{'delete' if a.delete else 'would delete'}  {match}  {replay:<42} {len(sizes):>6} files "
              f"{sum(sizes) / 2**20:>9.1f} MiB")
    freed = sum(objects[k] for k in result["delete"])
    print(f"\n{len(result['delete'])} of {len(objects)} files, {freed / 2**20:,.1f} MiB of "
          f"{sum(objects.values()) / 2**20:,.1f} MiB; kept: {len(result['keep'])} files")
    if a.delete:
        for i in range(0, len(result["delete"]), 1000):
            batch = [{"Key": k} for k in result["delete"][i:i + 1000]]
            s3.delete_objects(Bucket=BRONZE_BUCKET, Delete={"Objects": batch, "Quiet": True})
        print(f"deleted: {freed / 2**20:,.1f} MiB freed")
    else:
        print("nothing deleted: add --delete (make bronze-prune KEEP=3 DELETE=yes)")


if __name__ == "__main__":
    main()
