# Shortcuts (Linux/macOS/WSL). Without make, run the plain commands from README.md.
# Docker needs sudo on your machine?  make up DOCKER="sudo docker"
.DEFAULT_GOAL := help
.PHONY: help up down reset ps logs topics counts smoke lint test coverage check-config build ci data bronze replay check silver streaming streaming-stop gold gold-sql soda soda-silver soda-gold soda-demo app app-stop dagster dagster-stop evidence monitoring monitoring-stop benchmark benchmark-report bronze-prune demo demo-reset demo-stop

DOCKER ?= docker
COMPOSE = $(DOCKER) compose
KAFKA_BIN = $(COMPOSE) exec -e KAFKA_HEAP_OPTS="-Xmx128m" kafka /opt/kafka/bin
MATCH ?= m001
SC_ID ?= 1874553
SPEED ?= 60
ARGS ?=
ALL_PROFILES = --profile jobs --profile app --profile dagster --profile monitoring --profile demo
AM_TMP = $(CURDIR)/.cache/alertmanager
# the config checks use the images docker-compose.yml runs, so an image update is checked too
PROMETHEUS_IMAGE = $(shell grep -oE 'prom/prometheus:[^" ]+' docker-compose.yml | head -1)
ALERTMANAGER_IMAGE = $(shell grep -oE 'prom/alertmanager:[^" ]+' docker-compose.yml | head -1)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n",$$1,$$2}'

up: ## Start MinIO, Kafka, Kafka UI, Spark and the Bronze writer (creates .env if missing)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d

down: ## Stop (data kept), dashboard, Dagster, monitoring and the Control Center included
	$(COMPOSE) --profile app --profile dagster --profile monitoring --profile demo down

reset: ## Stop and DELETE all data (topics, buckets, Dagster history, metrics)
	$(COMPOSE) $(ALL_PROFILES) down -v

ps: ## Container status
	$(COMPOSE) ps -a

logs: ## Logs: make logs s=kafka
	$(COMPOSE) logs -f --tail=100 $(s)

topics: ## List Kafka topics
	$(KAFKA_BIN)/kafka-topics.sh --bootstrap-server localhost:9092 --list

counts: ## Messages per topic (sum of its partitions)
	$(KAFKA_BIN)/kafka-get-offsets.sh --bootstrap-server localhost:9092 | awk -F: '/^foot-/{n[$$1]+=$$3} END{for(t in n) print t, n[t]}' | sort

smoke: ## Check MinIO, buckets, Kafka, topics
	python scripts/smoke_test.py

lint: ## Ruff
	ruff check .

test: ## Unit tests (no Docker needed)
	python -m pytest -q

coverage: ## Unit tests with line coverage (CI adds the Soda tests and requires 90 %)
	python -m pytest -q --cov

# the same Prometheus and Alertmanager images as docker-compose.yml check their own configs
check-config: ## Validate docker-compose.yml, Prometheus rules and tests, Alertmanager config
	@test -f .env || cp .env.example .env
	$(COMPOSE) config -q
	$(DOCKER) run --rm --entrypoint /bin/promtool -v $(CURDIR)/monitoring/prometheus:/etc/prometheus:ro \
	  $(PROMETHEUS_IMAGE) check config /etc/prometheus/prometheus.yml
	$(DOCKER) run --rm --entrypoint /bin/promtool -v $(CURDIR)/monitoring/prometheus:/etc/prometheus:ro \
	  -w /etc/prometheus/tests $(PROMETHEUS_IMAGE) test rules alerts_test.yml
	@rm -rf $(AM_TMP) && mkdir -p $(AM_TMP)
	sed -e 's|__SMTP_PORT__|587|; s|__[A-Z_]*__|x|g; s|/tmp/alertmanager/|/tmp/am/|g' \
	  monitoring/alertmanager/alertmanager.yml.tmpl > $(AM_TMP)/alertmanager.yml
	cp monitoring/alertmanager/email.tmpl $(AM_TMP)/ && touch $(AM_TMP)/smtp_password
	$(DOCKER) run --rm --entrypoint /bin/amtool -v $(AM_TMP):/tmp/am:ro $(ALERTMANAGER_IMAGE) \
	  check-config /tmp/am/alertmanager.yml

build: ## Build every image of docker-compose.yml
	$(COMPOSE) $(ALL_PROFILES) build

ci: lint coverage check-config ## What CI runs, except the Soda tests and the image builds

data: ## Download + convert one match: make data MATCH=m001 SC_ID=1874553
	python -m ingestion.download_foot $(SC_ID)
	python -m ingestion.ingest_foot --match $(MATCH) --sc-id $(SC_ID)

bronze: ## Kafka -> MinIO bronze writer in this terminal (`make up` already runs it: service bronze-writer)
	python -m ingestion.bronze_writer

replay: ## Replay a match into Kafka: make replay MATCH=m001 SPEED=60
	python -m ingestion.producer_foot --match $(MATCH) --speed $(SPEED)

check: ## Compare bronze row counts with the prepared match
	python -m ingestion.check_bronze --match $(MATCH)

silver: ## Bronze -> Silver on the Spark cluster: make silver MATCH="m001 m002" [ARGS=--dry-run]
	$(COMPOSE) --profile jobs run --rm silver --match $(MATCH) $(ARGS)

streaming: ## Spark Structured Streaming: Kafka -> 5/15-minute live stats -> foot-live-stats (start BEFORE a replay)
	$(COMPOSE) --profile jobs run --rm -d -p 127.0.0.1:4040:4040 --name streaming-5min streaming

streaming-stop: ## Stop the streaming job (its checkpoint keeps the state for the next start)
	docker stop streaming-5min

gold: ## Silver -> Gold with dbt + DuckDB in Docker (models, tests, export to s3://gold): make gold [ARGS="--select gold_shots"]
	$(COMPOSE) --profile jobs run --rm dbt build --vars '{export_gold: true}' $(ARGS)

gold-sql: ## Query the Gold DuckDB file (read-only): make gold-sql Q="select * from gold_shots limit 5"
	$(COMPOSE) --profile jobs run --rm duckdb "$(Q)"

soda: ## Soda checks on Silver then Gold (exit code 1 if one fails): make soda
	$(COMPOSE) --profile jobs run --rm soda --layer all

soda-silver: ## Soda checks on the Silver Iceberg tables only
	$(COMPOSE) --profile jobs run --rm soda --layer silver

soda-gold: ## Soda checks on the Gold DuckDB file only
	$(COMPOSE) --profile jobs run --rm soda --layer gold

soda-demo: ## Show the checks catching damaged data ON PURPOSE (a copy is corrupted, nothing is written)
	$(COMPOSE) --profile jobs run --rm soda --layer silver --demo-failure
	$(COMPOSE) --profile jobs run --rm soda --layer gold --demo-failure

app: ## Dashboard (Streamlit) on http://localhost:8501 (needs `make gold`; `make soda` fills the quality page)
	$(COMPOSE) --profile app up -d --build app
	@echo "dashboard: http://localhost:8501"

app-stop: ## Stop the dashboard
	$(COMPOSE) --profile app stop app

evidence: ## Re-run the quality proofs (Live = Gold, Streaming = Gold, live delay, caught runs) -> docs/quality_evidence.yml
	python scripts/quality_evidence.py

dagster: ## Dagster webserver + daemon on http://localhost:3000 (a replay's end starts its match's chain)
	$(COMPOSE) --profile dagster up -d --build dagster-webserver dagster-daemon

dagster-stop: ## Stop Dagster (its history stays in the volume dagster-storage)
	$(COMPOSE) --profile dagster stop dagster-webserver dagster-daemon

monitoring: ## Prometheus, Alertmanager (emails), Grafana on http://localhost:3001 and the exporters (monitoring/README.md)
	$(COMPOSE) --profile monitoring up -d --build

monitoring-stop: ## Stop the monitoring (7 days of metrics stay in the volume prometheus-data)
	$(COMPOSE) --profile monitoring stop

benchmark: ## Measure throughput, latency, load and recovery (~50 min, laptop busy) -> data/benchmark + docs/performance.md
	python scripts/benchmark.py
	python scripts/benchmark_report.py

benchmark-report: ## Rebuild docs/performance.md and its charts from the last make benchmark results
	python scripts/benchmark_report.py

bronze-prune: ## Keep the last KEEP complete replays per match in Bronze (default 3); shows first, DELETE=yes deletes
	python scripts/bronze_prune.py --keep $(or $(KEEP),3) $(if $(filter yes,$(DELETE)),--delete,)

demo: ## Everything the demo needs, then the Control Center on http://localhost:8000 (safe to run again)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d
	$(COMPOSE) --profile dagster up -d --build dagster-webserver dagster-daemon
	$(COMPOSE) --profile app up -d --build app
	$(COMPOSE) --profile monitoring up -d --build
	@$(DOCKER) ps --format '{{.Names}}' | grep -qx streaming-5min || $(MAKE) --no-print-directory streaming
	$(COMPOSE) --profile demo up -d --build control-center
	@echo "MatchLens Control Center: http://localhost:8000"

demo-stop: ## Stop the Control Center (replays it started stop too)
	$(COMPOSE) --profile demo stop control-center

demo-reset: ## Replay m001-m004 once at x60, one after the other: each is in Bronze and rebuilt by Dagster
	for m in m001 m002 m003 m004; do python -m ingestion.producer_foot --match $$m --speed 60 || exit 1; done
