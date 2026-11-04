# spark (Phase 4, 7)
- `jobs/bronze_to_silver.py`: dedupe, fix out-of-pitch, join team, speed, sprint flag, `MERGE INTO`.
- `jobs/streaming_5min.py` (optional FOO-08): event-time windows of 5 min + watermark (document the choice).
- Iceberg time-travel demo: `SELECT ... FOR VERSION AS OF`.
- Make every job idempotent (re-run ⇒ no duplicates).
