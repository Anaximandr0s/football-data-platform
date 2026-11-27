# ADR 0003: real SkillCorner tracking data instead of generated data

- **Status:** accepted, 2026-11-04
- **Context:** the first version of the project generated fake matches with a simulator. Statistics computed on invented movement say nothing about football, and they cannot be checked.
- **Options:**
  1. Keep the simulator: full control, but every number is made up.
  2. Event data only (for example StatsBomb open data): real, but no positions, so no distance, speed, pressing or
     live pitch.
  3. SkillCorner open data: real broadcast tracking of A-League matches, 10 frames per second, MIT licence.
- **Decision:** SkillCorner open data, converted by `ingestion/ingest_foot.py` and replayed into Kafka as if it were
  live. The simulator and its sample data were removed (`a27e5ab`). The matches used are listed in
  [`data-sources.md`](../data-sources.md); only matches on a 105 x 68 pitch are kept.
- **Consequences:** goals and scores can be checked against official match reports (`docs/external_checks.yml`).
  The data has real limits, stated on the Sources and limits page: tracking covers about three quarters of each match
  (camera gaps), positions are estimated from the broadcast, and there is no corner event and no expected goals.
