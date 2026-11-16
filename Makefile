# Shortcuts (Linux/macOS/WSL). Without make, run the plain commands from README.md.
# Docker needs sudo on your machine?  make up DOCKER="sudo docker"
.DEFAULT_GOAL := help
.PHONY: help up down reset ps logs topics counts smoke lint test data bronze replay check silver gold gold-sql soda soda-silver soda-gold soda-demo app app-stop dagster dagster-stop

DOCKER ?= docker
COMPOSE = $(DOCKER) compose
KAFKA_BIN = $(COMPOSE) exec -e KAFKA_HEAP_OPTS="-Xmx128m" kafka /opt/kafka/bin
MATCH ?= m001
SC_ID ?= 1874553
SPEED ?= 60
ARGS ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-8s %s\n",$$1,$$2}'

up: ## Start MinIO, Kafka, Kafka UI, Spark and the Bronze writer (creates .env if missing)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d

down: ## Stop (data kept), dashboard and Dagster included
	$(COMPOSE) --profile app --profile dagster down

reset: ## Stop and DELETE all data (topics, buckets, Dagster history)
	$(COMPOSE) --profile app --profile dagster down -v

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

streaming: ## Spark Structured Streaming (FOO-08): Kafka -> 5/15-minute live stats -> foot-live-stats (start BEFORE a replay)
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

dagster: ## Dagster webserver + daemon on http://localhost:3000 (a replay's end starts its match's chain)
	$(COMPOSE) --profile dagster up -d --build dagster-webserver dagster-daemon

dagster-stop: ## Stop Dagster (its history stays in the volume dagster-storage)
	$(COMPOSE) --profile dagster stop dagster-webserver dagster-daemon
