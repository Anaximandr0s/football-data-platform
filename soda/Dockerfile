# Soda Core 3.5.6 with DuckDB 2.0. The Soda DuckDB connector pins duckdb==1.0.0, which cannot open the Gold file written
# by dbt (DuckDB 2.0) nor read Iceberg reliably: so the connector is installed WITHOUT its dependencies. Soda is given
# a DuckDB connection built by soda/run_checks.py (it does not create its own). Python 3.11 still ships distutils,
# which Soda 3.5 imports.
FROM python:3.11-slim
RUN pip install --no-cache-dir "soda-core==3.5.6" "duckdb>=2.0,<2.1" \
 && pip install --no-cache-dir --no-deps "soda-core-duckdb==3.5.6"
ENV PYTHONUNBUFFERED=1
WORKDIR /app
ENTRYPOINT ["python", "/app/soda/run_checks.py"]
CMD ["--layer", "all"]
