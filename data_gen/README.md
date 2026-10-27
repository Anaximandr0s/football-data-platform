# data_gen (Phase 1-2 · Person A)
- `ingest_foot.py`: roster (Faker), tracking (22 × 5400 = 118 800 rows), ~1 600 events. Fixed seed (`RANDOM_SEED`).
- `producer_foot.py --match m001 --speed 30`: replays into Kafka (`localhost:29092`), key = `player_id`.
- Realism rules: speed ≤ ~36 km/h, limited acceleration, positions clipped to 105 × 68 m.
- `tests/`: same seed ⇒ same output; speed and bounds respected.
Output goes to `data/generated/` (git-ignored). Push a small sample to `data/sample/`.
