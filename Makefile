# Convenience targets. `make help` lists everything.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

.PHONY: help run stop restart logs shell dev test lint format typecheck audit \
        cov build image compose-up compose-down compose-logs backup migrate \
        first-run

help:  ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ── Local dev (no Docker) ──────────────────────────────────────────────
dev:            ## Run the server in dev mode with hot reload.
	DEV=1 ./start_web_ui.sh

test:           ## Run the pytest suite (no coverage report).
	.venv/bin/pytest --no-cov

cov:            ## Run pytest with coverage, print report to terminal.
	.venv/bin/pytest --cov=backend --cov-report=term-missing

lint:           ## Ruff check.
	.venv/bin/ruff check backend/ tests/

format:         ## Ruff format (in place).
	.venv/bin/ruff format backend/ tests/

typecheck:      ## Mypy strict-ish check.
	.venv/bin/mypy backend/

audit:          ## pip-audit for CVEs in requirements.txt (strict).
	.venv/bin/pip-audit --requirement requirements.txt --strict

backup:         ## Snapshot the workspace DB (nightly cron uses this too).
	./scripts/backup_db.sh

migrate:        ## Run any outstanding yoyo migrations.
	.venv/bin/python -c "from backend import database, migrations; print(migrations.apply_migrations(database.DB_PATH))"

# ── Docker ─────────────────────────────────────────────────────────────
build:          ## Build the studio Docker image (studio:latest).
	docker build -t local-llm-studio:latest .

image: build    ## Alias for `build`.

compose-up: run
run:            ## docker compose up -d
	docker compose up -d

compose-down:
stop:           ## docker compose down (data persists on named volumes).
	docker compose down

restart:        ## docker compose restart studio
	docker compose restart studio

compose-logs:
logs:           ## Tail the studio container logs.
	docker compose logs -f studio

shell:          ## Open a shell inside the running studio container.
	docker compose exec studio /bin/bash

first-run:      ## Pull models, curate corpus, provision expert workspaces.
	./scripts/first_run.sh
