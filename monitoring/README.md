# Monitoring

Watches the machine, the containers, the streaming path and the data pipeline, and sends an email when something
breaks. Prometheus collects the numbers, Alertmanager sends the emails, Grafana shows four dashboards. Everything is a
file in this folder; nothing is set by clicking. It runs in its own compose profile, so it can be turned off.

## Run it

```bash
make monitoring        # Grafana http://localhost:3001 · Prometheus :9090 · Alertmanager :9093
make monitoring-stop
```

It needs, in `.env`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`, `GRAFANA_ADMIN_USER`,
`GRAFANA_ADMIN_PASSWORD` (see `.env.example`). Alertmanager and Grafana refuse to start, naming the variable, when one
is empty. Grafana takes the admin password from `.env` only the first time it starts (it then lives in the volume
`grafana-data`); change it later in Grafana itself.

## How it works

| Piece | What it reads | File |
|---|---|---|
| Prometheus | every target below, every 15 s; keeps 7 days | `prometheus/prometheus.yml` |
| node-exporter | the host: CPU, memory, disk | |
| cAdvisor | every container: CPU, memory against its `mem_limit`, restarts | |
| kafka-exporter | topic offsets, lag of the `bronze-writer` consumer group | |
| MinIO | its own metrics (`/minio/v2/metrics/cluster`) | |
| Spark | its own Prometheus endpoint on master, worker and the streaming driver (`spark/metrics.properties`) | |
| blackbox | do the app, Dagster and MinIO answer HTTP, does Kafka accept connections | `blackbox/blackbox.yml` |
| pipeline-exporter (ours) | Dagster runs and steps (GraphQL), dbt test results, Soda results per dimension, the Spark progress file, Gold freshness per match | `exporter/pipeline_exporter.py` |
| the app | its own Kafka consumer: lag and live delay (port 9108, not published) | `app/streamlit/live_feed.py` |
| alert rules | 14 alerts, each with what happened, where, and what to check | `prometheus/rules/alerts.yml` |
| recording rules | shared expressions and the 5 service levels (SLO) | `prometheus/rules/recording.yml` |
| Alertmanager | groups the alerts and sends the emails | `alertmanager/` |
| Grafana | 4 dashboards, built by `grafana/build_dashboards.py` | `grafana/` |

Two readers of Kafka keep no offsets in Kafka, so the Kafka exporter cannot see how far behind they are: Spark
Structured Streaming keeps them in its checkpoint, and the Live page's consumer commits nothing. Spark writes its
progress (rows per second, offsets behind) to `data/streaming/progress.json` (`spark/streaming/progress.py`), read by
the pipeline exporter; the app serves its own lag. The three appear together as `football:consumer_lag`.

The pipeline exporter computes freshness with the Data quality page's own function (`quality.freshness`), so the page
and the alert can never disagree.

### Alerts

| Alert | When |
|---|---|
| ContainerDown | a container of `make up` is not seen for 1 minute |
| ServiceDown | an exporter or Alertmanager does not answer Prometheus for 1 minute |
| ContainerRestarting | 2 restarts in 15 minutes |
| ContainerMemoryHigh | above 90 % of its `mem_limit` for 2 minutes |
| DiskSpaceLow | under 15 % free for 5 minutes |
| HostCpuHigh | above 85 % for 5 minutes |
| KafkaDown | Kafka refuses connections for 1 minute; mutes the two alerts below |
| ConsumerLagGrowing | during a replay, a reader's lag grew for 2 minutes |
| SparkStreamingStalled | during a replay, no progress from Spark for 2 minutes |
| WebServiceDown | the app, Dagster or MinIO does not answer for 1 minute |
| DagsterRunFailed | the latest run of a job and match failed |
| SodaCheckFailed | a Soda check failed (with its dimension) |
| DbtTestFailed | a dbt test failed |
| GoldStale | a replay ended more than 15 minutes ago and Gold is still not rebuilt |

Emails are grouped by alert and area (6 failed checks: one email), repeated every 4 hours while the problem lasts, and
followed by a "resolved" email when it ends.

### Service levels (SLO)

Measured over 7 days, the retention: live delay p95 under 2 s, Gold ready within 10 minutes of the final whistle, at
least 95 % of Dagster runs succeed, 100 % of the blocking checks pass, the app answers at least 99 % of the probes.

### Measured (2026-11-17)

- Damaged-data run: failed at 10:46:53 UTC, the two emails (Dagster run, 6 Soda checks with their dimension) sent at
  10:47:35, 42 s later. The normal run after a full replay: alerts ended at 11:03:56, "resolved" emails at 11:05:20.
- bronze-writer stopped: alert after 85 s, email after 113 s.
- During a replay at 10x: 173 Kafka messages/s, live delay p95 0.72 s, Spark batches about 9 s (trigger 5 s).
- Memory of the monitoring: 538 MiB at rest of 4,792 MiB for all 18 containers (Grafana 227, cAdvisor 111,
  Prometheus 82, pipeline exporter 50, Alertmanager 24, the three other exporters 43).

## Gmail app password

Gmail refuses your normal password from a program. Create an app password:

1. Turn on 2-Step Verification on the Google account that sends the alerts.
2. Open https://myaccount.google.com/apppasswords, name it "MatchLens alerts", create.
3. Copy the 16 characters into `.env`: `SMTP_PASSWORD=...`, with `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
   `SMTP_USER=` that Gmail address, `ALERT_EMAIL_TO=` the address that receives the alerts.
4. `make monitoring` (or `docker compose --profile monitoring up -d alertmanager` after a change).

Revoke it on the same page when the project ends. `.env` is git-ignored: the password never reaches the repository.

## Choices and trade-offs

- **MinIO metrics are public** (`MINIO_PROMETHEUS_AUTH_TYPE=public`). Anyone who can reach port 9000 can read them; here
  the port is published on 127.0.0.1 only, so that is this machine. In production, keep the default (`jwt`): generate a
  token with `mc admin prometheus generate`, store it as a secret, and give it to Prometheus (`bearer_token_file`).
  One more secret to rotate, but the metrics (bucket sizes, request rates) stay private.
- **cAdvisor is privileged** and reads the Docker socket and cgroups: it needs them to see the other containers.
- **The SMTP password** is in the Alertmanager container's environment (visible with `docker inspect`) and in a file
  inside it; it is never in a config file of the repository.
- **Links in the emails** point to `localhost`: they open on the machine running the platform.
- **Grafana plugins**: Grafana 13 starts one process per bundled data source (17-31 MiB each); all but Prometheus are
  disabled in `docker-compose.yml`.
- **cAdvisor timestamps are ignored** (`honor_timestamps: false`): with them, Prometheus keeps a stopped container's
  series for 5 minutes and ContainerDown fires 6 minutes late instead of about 1.5.

## Tests

`python -m pytest tests/monitoring` (the exporter on fixed Dagster, dbt, Soda and Spark data; every alert has its texts;
the dashboards in git match the script; every placeholder is filled), `tests/spark/test_streaming_progress.py`,
`tests/app/test_live_feed_metrics.py`. CI also checks the configs with the official tools and runs
`prometheus/tests/alerts_test.yml` (ContainerDown fires for a stopped container, with the texts of the email):

```bash
docker run --rm --entrypoint promtool -v $PWD/monitoring/prometheus:/etc/prometheus:ro prom/prometheus:v3.15.1 check config /etc/prometheus/prometheus.yml
```

## Limits

- One Prometheus, no long-term storage: 7 days, then the history is gone. The "7-day" service levels cover less right
  after a first start.
- If Prometheus or Alertmanager is down, no alert is sent: nothing watches the watcher.
- Spark's own metrics exist only while `make streaming` runs; its target is down otherwise, on purpose.
- ContainerRestarting counts every new start of a container, a `docker compose restart` included: cAdvisor sees when
  a container started, not why.
- The live delay counts only once the app's consumer has read every topic to its end: before, it re-reads old replays.
