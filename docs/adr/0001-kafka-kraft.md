# ADR 0001: Kafka in KRaft mode
- **Status:** accepted
- **Context:** 16 GB RAM budget; ZooKeeper would add a container.
- **Decision:** single-node Kafka in KRaft mode, auto topic creation disabled, topics created by `kafka-init`.
- **Consequences:** one fewer container; no replication (acceptable for a demo, document it in the report).
