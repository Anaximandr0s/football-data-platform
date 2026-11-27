# ADR 0005: every replay has an id, and only complete replays are stored

- **Status:** accepted, 2026-11-17 (`replay_id`), 2026-11-18 (partial replays)
- **Context:** the same match is replayed many times (demos, tests, the benchmark). Mixing two replays doubled the rows
  of a match, and a replay started at 88:00 that reached the final whistle was rebuilt into Silver and Gold as if it
  were a whole match.
- **Options:**
  1. Deduplicate everything in Silver: works for duplicates, not for a replay that misses 88 minutes.
  2. A Kafka header saying "partial": every reader (Bronze writer, Dagster sensor, Silver) would have to copy it on.
  3. Put it in the id that every message and every Bronze folder already carries.
- **Decision:** the producer gives each replay an id `<match>-<UTC start, YYYYMMDDTHHMMSSZ>`, sent in every message and
  used as a Bronze folder (`ingestion/replay_ids.py`). A replay is **complete** only if it starts at kick-off and
  reaches the final whistle. Any other replay gets the suffix `-partial`: it is shown live but the Dagster sensor,
  Silver, the Bronze check and `make bronze-prune` ignore it. The rule is in
  [`contrat_donnees.md`](../contrat_donnees.md), sections 5 and 6.
- **Consequences:** Silver reads exactly one replay folder per match, so a second demo never doubles a match. A partial
  replay never changes Gold. Checked live on 2026-11-18: `m004-20261118T124916Z-partial` reached 90:00 +4:18 and no
  Dagster run was created.
