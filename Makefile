.DEFAULT_GOAL := help
COMPOSE ?= docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

env: ## Create .env from .env.example (if missing)
	@test -f .env || (cp .env.example .env && echo ".env created - edit the passwords!")

up: env ## Start the platform
	$(COMPOSE) up -d

down: ## Stop the platform (keeps data)
	$(COMPOSE) down

reset: ## Stop and DELETE all volumes (clean slate)
	$(COMPOSE) down -v

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Follow logs (make logs s=kafka)
	$(COMPOSE) logs -f $(s)

topics: ## List Kafka topics
	$(COMPOSE) exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

smoke: ## Check that the base services answer
	bash scripts/smoke_test.sh

lint: ## Ruff lint
	ruff check .
