# Updating

## Docker Compose

```sh
git pull
docker compose pull
docker compose build --no-cache studio
docker compose up -d
```

Migrations apply automatically at server startup. Named volumes
persist `/data` and `/root/.ollama`, so no state is lost.

## Bare metal

```sh
git pull
.venv/bin/pip install --upgrade -r requirements.txt
make migrate
```

Then restart uvicorn (`Ctrl-C` and re-run `make dev` — or your process
manager).

## macOS `.app`

The tray app checks for updates on launch via `desktop/updater.py`,
polling `api.github.com/repos/OWNER/REPO/releases/latest`. If a newer
tag exists, a notification appears with a download link. We never
auto-download or auto-install.

Manual upgrade:

```sh
git pull
make bundle          # produces dist/LocalLLMStudio.app
# optional: make sign notarize   (Apple Dev cert required)
```

Then drag `dist/LocalLLMStudio.app` into `/Applications` — user data
lives under `~/Library/Application Support/LocalLLMStudio/` and
survives the swap.

## Rolling back

Tags are the anchor:

```sh
git checkout v0.8.0
docker compose build --no-cache studio
docker compose up -d
```

If a migration was applied in the newer version and you need to roll
back, restore the DB from a `scripts/backup_db.sh` snapshot taken
before the upgrade.

## What breaks on upgrade

`Plan/PROFESSIONAL_90DAY_PLAYBOOK.md` tracks each release. Read the
`CHANGELOG` (once we have one) or the tag messages
(`git tag -n99 v0.X.0`) before upgrading in a working environment.
