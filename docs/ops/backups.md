# Backups

The workspace is a single SQLite file — `backend/workspace.db` (bare
metal) or `/data/workspace.db` (Docker). Losing it loses every
conversation, artifact reference, and setting.

## Automated snapshot

`scripts/backup_db.sh` uses SQLite's `.backup` command (safe against a
running server; no `flock` needed):

```sh
make backup                     # writes to <data>/backups/YYYYMMDD_HHMMSS.sqlite
```

Retention: last 30 snapshots by default. Adjust `RETAIN=` at the top of
the script.

## Nightly cron

Install once:

```sh
crontab -e
```

Add:

```
0 3 * * *  cd /path/to/local-llm-studio && ./scripts/backup_db.sh >> /var/log/studio-backup.log 2>&1
```

Or as a launchd job on macOS — see the LaunchAgent stub in
`scripts/backup_db.sh`'s header comment.

## Restore drill

**Once a month**, verify a backup actually opens:

```sh
cp backend/backups/20260901_030000.sqlite /tmp/restore-check.db
sqlite3 /tmp/restore-check.db 'select count(*) from conversations;'
sqlite3 /tmp/restore-check.db 'select name from projects;'
```

## Migrating between machines

```sh
# On source
make stop                       # or stop uvicorn
cp backend/workspace.db /tmp/studio-move.db
# transfer /tmp/studio-move.db …
# On target
mv /tmp/studio-move.db backend/workspace.db
make run
```

The database is self-contained — no external state to reconcile.
Uploads/artifacts under `backend/uploads/` and `backend/artifacts/`
should be moved alongside.

## Migrations

`yoyo` handles schema changes. On startup the server runs
`migrations.apply_migrations(database.DB_PATH)`. Manual apply:

```sh
make migrate
```

Migrations are forward-only; rollback means restoring from a backup.
