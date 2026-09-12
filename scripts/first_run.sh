#!/usr/bin/env bash
# Local LLM Studio — first-run bootstrapper.
#
# Assumes `docker compose up -d` has been run and both containers are up.
# Pulls required Ollama models, curates the corpus, and provisions the
# two expert workspaces. Safe to re-run: every step is idempotent.
#
# Usage:  ./scripts/first_run.sh
#
# Env overrides:
#   OLLAMA_CONTAINER  default: studio-ollama
#   STUDIO_CONTAINER  default: studio-app
#   MODELS            default: "nomic-embed-text qwen2.5:32b llama3.2:1b"
#   SKIP_MODELS       set to 1 to skip the (slow) model pull step
#   SKIP_CORPUS       set to 1 to skip corpus curation
#   SKIP_WORKSPACES   set to 1 to skip expert workspace provisioning

set -euo pipefail

OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-studio-ollama}"
STUDIO_CONTAINER="${STUDIO_CONTAINER:-studio-app}"
MODELS="${MODELS:-nomic-embed-text qwen2.5:32b llama3.2:1b}"

log()  { printf '\033[1;36m[first-run]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[first-run]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[first-run]\033[0m %s\n' "$*" >&2; exit 1; }

require_container() {
  local name="$1"
  if ! docker inspect --type=container "$name" >/dev/null 2>&1; then
    die "container '$name' not found. Run 'docker compose up -d' first."
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != "true" ]; then
    die "container '$name' is not running. Run 'docker compose up -d' first."
  fi
}

log "== Local LLM Studio first-run =="
require_container "$OLLAMA_CONTAINER"
require_container "$STUDIO_CONTAINER"

# ── 1. Models ──────────────────────────────────────────────────────────
if [ "${SKIP_MODELS:-0}" = "1" ]; then
  warn "SKIP_MODELS=1 — skipping model pull step"
else
  log "1/3 pulling models: $MODELS  (this can take a while on first run)"
  for m in $MODELS; do
    log "  → $m"
    docker exec "$OLLAMA_CONTAINER" ollama pull "$m"
  done
fi

# ── 2. Corpus ──────────────────────────────────────────────────────────
if [ "${SKIP_CORPUS:-0}" = "1" ]; then
  warn "SKIP_CORPUS=1 — skipping corpus curation"
else
  log "2/3 curating corpus (idempotent, skips already-cloned repos)"
  docker exec "$STUDIO_CONTAINER" python scripts/curate_corpus.py
fi

# ── 3. Expert workspaces ───────────────────────────────────────────────
if [ "${SKIP_WORKSPACES:-0}" = "1" ]; then
  warn "SKIP_WORKSPACES=1 — skipping expert workspace provisioning"
else
  log "3/3 building expert workspaces (Security + Coding)"
  docker exec "$STUDIO_CONTAINER" python scripts/build_expert_workspaces.py
fi

# ── Report auth token so the user can log in ───────────────────────────
if docker exec "$STUDIO_CONTAINER" test -f /data/token 2>/dev/null; then
  token="$(docker exec "$STUDIO_CONTAINER" cat /data/token 2>/dev/null || true)"
  if [ -n "$token" ]; then
    log ""
    log "Auth token (paste into http://127.0.0.1:8080/auth?token=<token>):"
    printf '  %s\n' "$token"
  fi
fi

log ""
log "Done. Open http://127.0.0.1:8080"
