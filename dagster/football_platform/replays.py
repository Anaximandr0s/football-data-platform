"""When is a replay over? Pure functions over decoded Kafka messages, used by the sensor (sensors.py).

A replay is over when its tracking reaches the last second of the match (`p2_end_ts` of the replay's own foot-matches
message): `ts` is the second of the match, so this holds at any replay speed. A partial replay (started after kick-off,
ingestion/replay_ids.py) is never over for the pipeline: it would build a match without its first minutes.
"""
from collections.abc import Iterable

from ingestion import replay_ids


def match_of(replay_id: str) -> str:
    """"m001-20261116T101503Z" -> "m001"."""
    return replay_ids.match_of(replay_id)


def replay_ends(matches: Iterable[tuple[str | None, dict]]) -> dict[str, tuple[str, int]]:
    """(replay_id header, foot-matches record) -> {replay_id: (match_id, p2_end_ts)}; messages without the header
    (written before replay_id existed) are ignored."""
    return {rid: (rec["match_id"], int(rec["p2_end_ts"])) for rid, rec in matches if rid is not None}


def finished(ends: dict[str, tuple[str, int]], tracking: Iterable[tuple[str | None, int]]) -> set[str]:
    """The complete replays (from kick-off) whose tracking (replay_id, ts) reached the last second of their match."""
    return {rid for rid, ts in tracking if rid in ends and ts >= ends[rid][1] and not replay_ids.is_partial(rid)}
