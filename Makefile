.PHONY: help setup up down restart logs build test lint clean status config up-prod chat setup-topics health jira-forge-test

# Default environment variables
include .env.example
-include .env

help:
	@echo "Available commands:"
	@echo "  make up        - Start the local development stack"
	@echo "  make up-prod   - Start using production overrides"
	@echo "  make down      - Stop the stack"
	@echo "  make restart   - Restart the stack"
	@echo "  make logs      - Show logs from all services"
	@echo "  make build     - Build all locally built images"
	@echo "  make test      - Run tests in the appropriate containers"
	@echo "  make chat      - Alias for make test"
	@echo "  make lint      - Run linters in the appropriate containers"
	@echo "  make clean     - Stop the stack and remove volumes"
	@echo "  make status    - Show container and health status"
	@echo "  make config    - Render and validate the merged Compose configuration"
	@echo "  make setup-topics - Create the required Kafka topics for the event pipeline"
	@echo "  make setup     - Create .env and start the local stack"
	@echo "  make health    - Verify local frontend and backend"
	@echo "  make jira-forge-test - Validate the private Jira Forge app"

setup:
	@test -f .env || cp .env.example .env
	$(MAKE) up
	$(MAKE) setup-topics

up:
	docker compose -f compose.yaml -f compose.override.yaml up -d --build --renew-anon-volumes

up-prod:
	docker compose -f compose.yaml -f compose.prod.yaml up -d

down:
	docker compose down

restart:
	docker compose -f compose.yaml -f compose.override.yaml restart

logs:
	docker compose -f compose.yaml -f compose.override.yaml logs -f

build:
	docker compose -f compose.yaml build

test:
	docker compose -f compose.yaml -f compose.override.yaml exec backend bash -c "PYTHONPATH=/app pytest tests/"
	docker compose -f compose.yaml -f compose.override.yaml exec ingestion-proxy bash -c "PYTHONPATH=/app pytest tests/"
	docker compose -f compose.yaml -f compose.override.yaml exec pipeline bash -c "PYTHONPATH=/app pytest tests/"
	docker compose -f compose.yaml -f compose.override.yaml exec frontend npm run lint

lint:
	docker compose -f compose.yaml -f compose.override.yaml exec backend python -m compileall -q .
	docker compose -f compose.yaml -f compose.override.yaml exec frontend npm run lint

jira-forge-test:
	npm --prefix integrations/jira-forge ci
	npm --prefix integrations/jira-forge test
	npm --prefix integrations/jira-forge run validate-manifest
	npm --prefix integrations/jira-forge audit --omit=dev

chat: test

clean:
	@test "$(CONFIRM)" = "destroy" || (echo "Refusing to delete volumes. Run: make clean CONFIRM=destroy"; exit 1)
	docker compose down -v

health:
	@for attempt in $$(seq 1 30); do \
		if curl --fail --silent http://localhost:8000/api/v1/health >/dev/null && \
		   curl --fail --silent http://localhost:3000 >/dev/null; then \
			echo "Local frontend and backend are healthy"; exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "Local stack did not become healthy" >&2; exit 1

status:
	docker compose ps

config:
	docker compose -f compose.yaml -f compose.override.yaml config

setup-topics:
	@echo "Waiting for Kafka to be ready..."
	@sleep 5
	@for topic in received validated normalized enriched clustered distinct dead_letter_queue alert_processing_events; do \
		docker compose -f compose.yaml -f compose.override.yaml exec -T kafka \
		/opt/kafka/bin/kafka-topics.sh --create --if-not-exists \
		--bootstrap-server kafka:9092 --topic $$topic; \
	done
	@echo "Kafka topics provisioned."
