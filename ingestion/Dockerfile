# The Bronze writer (service bronze-writer, started by `make up`): Kafka -> MinIO, same pins as requirements.txt.
FROM python:3.15-slim
RUN pip install --no-cache-dir "pandas>=3.1,<4" "pyarrow>=26,<27" "confluent-kafka>=2.16,<3" "boto3>=1.43,<2"
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
WORKDIR /app
ENTRYPOINT ["python", "-m", "ingestion.bronze_writer"]
