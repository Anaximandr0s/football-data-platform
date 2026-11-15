# dbt-core + dbt-duckdb (DuckDB is a library inside this image, not a server). Used by the `dbt` and `duckdb`
# services of docker-compose.yml (profile "jobs"). Python 3.12: the version dbt supports best.
FROM python:3.12-slim
# duckdb is pinned like in soda/Dockerfile: the Gold file written here must be readable there.
RUN pip install --no-cache-dir "dbt-core>=1.10,<1.13" "dbt-duckdb>=1.11,<1.12" "duckdb>=2.0,<2.1"
ENV DBT_PROFILES_DIR=/app/dbt \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    PYTHONUNBUFFERED=1
WORKDIR /app/dbt
ENTRYPOINT ["dbt"]
CMD ["--help"]
