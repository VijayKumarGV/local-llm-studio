#!/usr/bin/env bash
# Nightly SQLite backup for Local LLM Studio.
#
# * Uses `sqlite3 .backup` (online, safe even while the server is running).
# * Gzips the result to $BACKUP_DIR/workspace_YYYYMMDD_HHMMSS.db.gz.
# * Retains daily backups for RETAIN_DAYS (default 30).
# * On the 1st of the month, runs a restore drill: decompress into a temp
#   file, verify project count, delete.
#
# Install (macOS):
#   crontab -e
#   # append:
#   0 3 * * * cd "/Users/avishwakarma/Desktop/llm model" && ./scripts/backup_db.sh \
#             >> "$HOME/Library/Application Support/LocalLLMStudio/backup.log" 2>&1
#
# Env overrides:
#   BACKUP_DIR   — where to write backups (default: ~/Library/Application Support/LocalLLMStudio/backups)
#   RETAIN_DAYS  — how many days of backups to keep (default: 30)
#   DB_PATH      — path to the source workspace.db (default: <repo>/backend/workspace.db)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${DB_PATH:-$ROOT/backend/workspace.db}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Library/Application Support/LocalLLMStudio/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
  echo "[backup] source DB not found at $DB_PATH — nothing to back up"
  exit 0
fi

STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/workspace_$STAMP.db"

# Online backup: locks briefly, safe with a live server.
sqlite3 "$DB_PATH" ".backup '$DEST'"

gzip -9 "$DEST"
DEST_GZ="$DEST.gz"
SIZE=$(du -h "$DEST_GZ" | cut -f1)
echo "[backup] wrote $DEST_GZ ($SIZE)"

# Retention prune.
find "$BACKUP_DIR" -type f -name "workspace_*.db.gz" -mtime "+$RETAIN_DAYS" -print -delete \
  | sed 's/^/[backup] pruned: /'

# Monthly restore drill on the 1st.
if [ "$(date +%d)" = "01" ]; then
  echo "[drill] monthly restore drill starting"
  TMP=$(mktemp -t studio_drill_XXXXXX)
  gunzip -c "$DEST_GZ" > "$TMP"
  if PROJECTS=$(sqlite3 "$TMP" "SELECT COUNT(*) FROM projects;" 2>/dev/null); then
    CONVOS=$(sqlite3 "$TMP" "SELECT COUNT(*) FROM conversations;" 2>/dev/null || echo "?")
    MSGS=$(sqlite3 "$TMP" "SELECT COUNT(*) FROM messages;" 2>/dev/null || echo "?")
    echo "[drill] restore OK — projects=$PROJECTS conversations=$CONVOS messages=$MSGS"
  else
    echo "[drill] RESTORE FAILED for $DEST_GZ — investigate immediately" >&2
    exit 1
  fi
  rm -f "$TMP"
fi
