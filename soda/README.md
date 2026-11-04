# soda (Phase 6)
Soda Core checks (`soda-core-duckdb`) in `checks/`:
- `x between 0 and 105`, `y between 0 and 68`
- `speed_kmh <= 40`
- 22 players per (`match_id`, `ts`)
- freshness and row counts
**Demo a failure on purpose** and show Dagster blocking downstream steps.
