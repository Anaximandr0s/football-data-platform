# kafka (Phase 2-3 · Person A)
Topics are created by the `kafka-init` service (see `docker-compose.yml`).
Consumer groups: `bronze-writer` (to MinIO), `live-gateway` (to the 3D page), `streamlit-live`.
Add the `bronze-writer` consumer here.

## bronze_writer.py
`pip install confluent-kafka pyarrow pandas boto3`, export `MINIO_ROOT_PASSWORD` (same as `.env`), then `python kafka/bronze_writer.py`.
Writes Parquet micro-batches to `s3://bronze/{tracking,events}/match_id=<id>/`.
