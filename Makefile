# Convenience targets. `make help` lists everything.

.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

.PHONY: help run stop restart logs shell dev test lint format typecheck audit \
        cov build image compose-up compose-down compose-logs backup migrate \
        first-run bundle sign notarize dmg release-artifacts

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
	.venv/bin/ruff check backend/ tests/ desktop/

format:         ## Ruff format (in place).
	.venv/bin/ruff format backend/ tests/ desktop/

typecheck:      ## Mypy strict-ish check.
	.venv/bin/mypy backend/ desktop/

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

# ── macOS .app packaging ───────────────────────────────────────────────
# Requires:  pip install -r desktop/requirements.txt
# Sign/notarize steps require an Apple Developer ID cert + these env vars:
#   APPLE_DEV_ID    "Developer ID Application: NAME (TEAMID)"
#   APPLE_ID        Apple ID email
#   APPLE_TEAM_ID   10-char team identifier
#   APPLE_PASSWORD  app-specific password from appleid.apple.com

APP_BUNDLE := dist/LocalLLMStudio.app
DMG_OUT    := dist/LocalLLMStudio.dmg

bundle:         ## Build dist/LocalLLMStudio.app (unsigned).
	.venv/bin/python desktop/build_app.py

sign:           ## codesign the .app bundle with APPLE_DEV_ID.
	@test -n "$$APPLE_DEV_ID" || (echo "APPLE_DEV_ID not set" && exit 1)
	@test -d "$(APP_BUNDLE)" || (echo "$(APP_BUNDLE) not built — run 'make bundle' first" && exit 1)
	codesign --deep --force --options runtime --timestamp \
	  --sign "$$APPLE_DEV_ID" "$(APP_BUNDLE)"
	codesign --verify --deep --strict --verbose=2 "$(APP_BUNDLE)"

notarize:       ## Submit the signed .app for notarization + staple the ticket.
	@test -n "$$APPLE_ID" -a -n "$$APPLE_TEAM_ID" -a -n "$$APPLE_PASSWORD" \
	  || (echo "APPLE_ID / APPLE_TEAM_ID / APPLE_PASSWORD must be set" && exit 1)
	ditto -c -k --keepParent "$(APP_BUNDLE)" "$(APP_BUNDLE).zip"
	xcrun notarytool submit "$(APP_BUNDLE).zip" \
	  --apple-id "$$APPLE_ID" --team-id "$$APPLE_TEAM_ID" \
	  --password "$$APPLE_PASSWORD" --wait
	xcrun stapler staple "$(APP_BUNDLE)"
	xcrun stapler validate "$(APP_BUNDLE)"

dmg:            ## Build a .dmg installer around the .app (needs create-dmg).
	@command -v create-dmg >/dev/null || (echo "install with: brew install create-dmg" && exit 1)
	create-dmg --volname "Local LLM Studio" --window-size 500 300 \
	  --icon "LocalLLMStudio.app" 125 130 --app-drop-link 375 130 \
	  "$(DMG_OUT)" "$(APP_BUNDLE)"

release-artifacts: bundle sign notarize dmg  ## Full local release build.
	@echo "Artifacts ready in dist/:"
	@ls -lh dist/
