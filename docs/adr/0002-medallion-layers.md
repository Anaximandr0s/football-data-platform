# ADR 0002: Bronze / Silver / Gold
- **Status:** accepted
- **Decision:** Bronze = raw in MinIO partitioned by `match_id`; Silver = Iceberg (Spark); Gold = dbt on DuckDB, grain documented per table.
- **Risk:** DuckDB reading Iceberg on MinIO. Fallback: Spark also writes a Parquet mirror of Silver.
