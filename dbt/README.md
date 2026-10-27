# dbt (Phase 5 · Person B)
dbt-core + dbt-duckdb. Layers: `models/staging` then `models/marts` (Gold).
Every Gold model documents its **grain** in `schema.yml`. Use incremental models and tests
(`unique`, `not_null`, `relationships`, `accepted_values`). `dbt docs generate` gives the lineage.
Risk: DuckDB reading Iceberg on MinIO; fallback = Parquet mirror of Silver.
