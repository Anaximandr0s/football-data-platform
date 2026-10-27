# Architecture

## Two paths, three layers
- **Batch path** (Dagster): Bronze → Silver → Gold, for post-match analytics.
- **Stream path**: Kafka → live display (and optional Spark Structured Streaming 5-min stats).

```mermaid
flowchart TB
  subgraph Sources
    S1[ingest_foot.py]:::a --> S2[producer_foot.py]:::a
  end
  S2 --> K[(Kafka KRaft<br/>foot-tracking key=player_id<br/>foot-events)]:::a
  K -->|group bronze-writer| B[(Bronze · MinIO<br/>partition match_id)]:::a
  B --> SI[(Silver · Spark + Iceberg<br/>MERGE · time travel)]:::a
  SI --> G[(Gold · dbt + DuckDB)]:::b
  Q[Soda checks]:::b -.-> G
  D[Dagster]:::b -.-> SI & G & Q
  K -->|Spark Structured Streaming| W[5-min window stats]:::a
  K -->|group live-gateway| API[FastAPI WebSocket]:::b --> WEB[3D live page]:::b
  G --> ST[Streamlit + mplsoccer]:::b
  classDef a fill:#dbeafe,stroke:#1d4ed8;
  classDef b fill:#dcfce7,stroke:#15803d;
```
Blue = Person A · Green = Person B.

## Conventions
- Pitch 105 × 68 m, origin bottom-left, metres.
- Kafka key = `player_id` → ordering per player.
- Buckets: `bronze`, `silver`, `warehouse`.

## Memory budget (16 GB laptop)
| Service | Limit |
|---|---|
| Kafka | 1 GB |
| Kafka UI | 0.5 GB |
| MinIO | 0.5 GB |
| Spark (local mode) | ~3 GB |
| Dagster (web + daemon + db) | ~1.5 GB |
| Streamlit / API / web3d | ~1 GB |

Run the streaming job only when demonstrating it.

## Tool justification (for the report)
| Tool | Problem solved that others don't |
|---|---|
| Kafka | ordered per-player stream, replay, several independent consumer groups |
| MinIO | S3-compatible storage for raw files and Iceberg |
| Iceberg | MERGE for corrections, time travel, schema evolution |
| dbt | SQL models + tests + docs + lineage |
| Soda | production data-quality checks that can block the pipeline |
| Dagster | scheduling, retries, run history, asset checks |
| mplsoccer | football pitch drawing |
