# Shortcuts (Linux/macOS/WSL). Without make, run the plain commands from README.md.
# Docker needs sudo on your machine?  make up DOCKER="sudo docker"
.DEFAULT_GOAL := help
.PHONY: help up down reset ps logs topics counts smoke lint test data bronze replay check

DOCKER ?= docker
COMPOSE = $(DOCKER) compose
KAFKA_BIN = $(COMPOSE) exec -e KAFKA_HEAP_OPTS="-Xmx128m" kafka /opt/kafka/bin
MATCH ?= m001
SC_ID ?= 1874553
SPEED ?= 60

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-8s %s\n",$$1,$$2}'

up: ## Start MinIO + Kafka + Kafka UI (creates .env if missing)
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d

down: ## Stop (data kept)
	$(COMPOSE) down

reset: ## Stop and DELETE all data (topics, buckets)
	$(COMPOSE) down -v

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

bronze: ## Kafka -> MinIO bronze writer (leave running, Ctrl+C to stop)
	python -m ingestion.bronze_writer

replay: ## Replay a match into Kafka: make replay MATCH=m001 SPEED=60
	python -m ingestion.producer_foot --match $(MATCH) --speed $(SPEED)

check: ## Compare bronze row counts with the prepared match
	python -m ingestion.check_bronze --match $(MATCH)