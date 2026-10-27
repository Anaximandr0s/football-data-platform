# Live gateway (FastAPI)
- `WS /ws/live`: pushes one JSON frame per tick (22 positions, score, minute).
- `GET /stats/player/{id}`: Gold stats from DuckDB.
- Kafka consumer group: `live-gateway`.
