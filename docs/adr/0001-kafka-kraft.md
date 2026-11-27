# ADR 0001: Kafka in KRaft mode, one node

- **Status:** accepted, 2026-10-27
- **Context:** the whole platform runs on one laptop (16 GB of RAM) next to Spark, MinIO, Dagster and the monitoring.
  Kafka is the entry point of every message, live and stored.
- **Options:**
  1. Kafka with ZooKeeper: one more container to run and watch.
  2. Kafka in KRaft mode: the broker is also its own controller.
  3. Another broker (Redpanda, RabbitMQ): Spark's Kafka source, Kafka UI and the exporters are built for Kafka.
- **Decision:** one Kafka node in KRaft mode (`KAFKA_PROCESS_ROLES: broker,controller`). Automatic topic creation is
  off; `kafka-init` creates the five replay topics from `KAFKA_TOPICS` (`foot-tracking` with 3 partitions, the others
  with 1) and the compacted topic `foot-live-stats`. Messages are kept 7 days (`KAFKA_LOG_RETENTION_HOURS: 168`).
- **Consequences:** one container fewer. Replication factor 1: if the node's disk is lost, the messages are lost. That
  is acceptable here because Bronze keeps every message and a match can be replayed again from the prepared files.
  A typo in a topic name fails instead of creating a new topic.
