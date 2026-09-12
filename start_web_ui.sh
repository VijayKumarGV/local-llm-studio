#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Prefer Homebrew Python 3.12 (widely supported by ML/PDF/HTTP wheels).
# You can override with PYTHON=/path/to/python3.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for cand in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.13; do
    [ -x "$cand" ] && PYTHON="$cand" && break
  done
fi
if [ -z "$PYTHON" ] || ! [ -x "$PYTHON" ]; then
  PYTHON="$(command -v python3.12 || command -v python3 || true)"
fi
if ! [ -x "$PYTHON" ]; then
  echo "[-] python3.12 not found. Install via: brew install python@3.12"
  exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[start_web_ui] Python $PY_VER at $PYTHON"

# Recreate venv if missing or wrong Python version
VENV=".venv"
REQS="requirements.txt"
NEED_INSTALL=0
# Require ≥3.12 and <3.14 to match pyproject constraints.
if ! "$VENV/bin/python" -c "import sys; assert (3,12) <= sys.version_info < (3,14)" 2>/dev/null; then
  echo "[start_web_ui] Creating fresh venv with $PYTHON..."
  rm -rf "$VENV"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/pip" install --upgrade pip --quiet
  NEED_INSTALL=1
fi

# Reinstall deps if requirements.txt is newer than the stamp
STAMP="$VENV/.reqs.stamp"
if [ ! -f "$STAMP" ] || [ "$REQS" -nt "$STAMP" ]; then
  NEED_INSTALL=1
fi
if [ "$NEED_INSTALL" = "1" ]; then
  echo "[start_web_ui] Installing dependencies from $REQS..."
  "$VENV/bin/pip" install -r "$REQS" --quiet
  touch "$STAMP"
fi

# Start Ollama if not already running
if ! curl -sf -m 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "[start_web_ui] Ollama not running — starting it..."
  # Try Homebrew location first, then PATH
  OLLAMA_BIN=""
  for p in /opt/homebrew/opt/ollama/bin/ollama /opt/homebrew/bin/ollama /usr/local/bin/ollama; do
    [ -x "$p" ] && OLLAMA_BIN="$p" && break
  done
  [ -z "$OLLAMA_BIN" ] && OLLAMA_BIN="$(command -v ollama 2>/dev/null || true)"
  if [ -z "$OLLAMA_BIN" ]; then
    echo "[-] Ollama not found. Install: brew install ollama"
    echo "    Then: ollama pull qwen2.5:32b   (or any model)"
    exit 1
  fi
  nohup "$OLLAMA_BIN" serve >"$TMPDIR/ollama.log" 2>&1 &
  echo "[start_web_ui] Waiting for Ollama..."
  for i in $(seq 1 20); do
    curl -sf -m 1 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

# Print available models
echo "[start_web_ui] Installed models:"
curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null \
  | python3 -c "import json,sys; [print('  -', m['name']) for m in json.load(sys.stdin).get('models', [])]" \
  2>/dev/null || echo "  (none yet — run: ollama pull qwen2.5:32b)"

echo ""
echo "[start_web_ui] Launching Studio at http://127.0.0.1:8080"
echo "[start_web_ui] Press Ctrl+C to stop."
echo ""

RELOAD_FLAG=""
if [ "${DEV:-}" = "1" ] || [ "${RELOAD:-}" = "1" ]; then
  RELOAD_FLAG="--reload --reload-dir backend --reload-dir static"
  echo "[start_web_ui] Dev mode: auto-reload on file changes."
fi

exec "$VENV/bin/python" -m uvicorn backend.server:app \
  --host 127.0.0.1 \
  --port 8080 \
  --log-level "${LOG_LEVEL:-warning}" \
  $RELOAD_FLAG
