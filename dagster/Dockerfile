# Dagster webserver and daemon, and the runs they launch: the Silver Spark driver (spark-submit to the cluster, so Java
# 17 and the same Spark version as the cluster), dbt + DuckDB for Gold, Soda for the checks, the Kafka client for the
# sensor. Python 3.11: Dagster 1.13 needs 3.11+, Soda 3.5 still imports distutils (gone in 3.12). bookworm: Java 17.
FROM python:3.15-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless procps \
 && rm -rf /var/lib/apt/lists/*
# protobuf < 7: dbt needs it, and grpcio-health-checking (Dagster) newer than 1.81 needs 7.
RUN pip install --no-cache-dir \
      "dagster==1.13.30" "dagster-webserver==1.13.30" "dagster-dbt==0.29.30" "protobuf>=6,<7" \
      "pyspark==4.0.0" \
      "dbt-core>=1.10,<1.13" "dbt-duckdb>=1.11,<1.12" "duckdb>=2.0,<2.1" "pandas>=3.1,<4" \
      "soda-core==3.5.6" "pyarrow>=26,<27" "confluent-kafka>=2.16,<3" "boto3>=1.43,<2" \
 && pip install --no-cache-dir --no-deps "soda-core-duckdb==3.5.6"
ENV DAGSTER_HOME=/opt/dagster/home \
    PYTHONPATH=/app:/app/dagster \
    DBT_PROFILES_DIR=/app/dbt \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    PYTHONUNBUFFERED=1
COPY dagster.yaml workspace.yaml /opt/dagster/home/
WORKDIR /app
