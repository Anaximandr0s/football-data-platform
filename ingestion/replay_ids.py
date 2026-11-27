"""replay_ids.py: the id every message of a replay carries (Kafka header replay_id, Bronze folder replay_id=...).

    m001-20261118T120000Z           a replay from kick-off: if it reaches the final whistle, it is a complete match
    m001-20261118T120000Z-partial   a replay started later (--start): live only, never stored as a match

Sorting ids sorts replays in time. Silver, the Dagster sensor and make bronze-prune ignore partial replays: a match
built from one would miss its first minutes."""

import datetime as dt

PARTIAL = "-partial"


def make(match_id: str, started: dt.datetime, partial: bool = False) -> str:
    return f"{match_id}-{started.astimezone(dt.UTC):%Y%m%dT%H%M%SZ}" + (PARTIAL if partial else "")


def is_partial(replay_id: str) -> bool:
    return replay_id.endswith(PARTIAL)


def match_of(replay_id: str) -> str:
    """ "m001-20261118T120000Z(-partial)" -> "m001"."""
    return replay_id.removesuffix(PARTIAL).rsplit("-", 1)[0]
