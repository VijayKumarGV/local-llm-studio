# Install

Two supported paths: the Docker stack for a one-command install, or a
bare-metal virtualenv for local development.

## Requirements

- macOS (primary), Linux (Docker path), Windows (Docker path).
- Python 3.12.
- Ollama — installed separately (see [ollama.com](https://ollama.com/)).
- 16 GB RAM minimum for small models; 32 GB+ recommended for 32B-class.

## A. Docker Compose (recommended)

Ships an Ollama container + the studio container, both bound to
`127.0.0.1` only.

```sh
git clone https://github.com/VijayKumarGV/local-llm-studio.git
cd local-llm-studio
docker compose up -d
./scripts/first_run.sh    # pulls models, curates corpus, provisions workspaces
```

Then open <http://127.0.0.1:8080>. Auth token:

```sh
docker compose exec studio cat /data/token
```

Paste the token at <http://127.0.0.1:8080/auth?token=...> to bootstrap
the cookie.

## B. Bare metal (dev)

```sh
git clone https://github.com/VijayKumarGV/local-llm-studio.git
cd local-llm-studio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Start Ollama in one terminal:

```sh
ollama serve
```

Studio in another:

```sh
make dev            # or: .venv/bin/uvicorn backend.server:app --reload
```

Auth token appears in the log line
`[auth] first-run token generated at …` — or read `backend/token` and
visit `/auth?token=...`.

## C. macOS `.app` bundle

For non-technical users:

```sh
pip install -r desktop/requirements.txt
make bundle             # → dist/LocalLLMStudio.app
open dist/LocalLLMStudio.app
```

First launch is unsigned; right-click → Open to bypass Gatekeeper.
See [`desktop/README.md`](https://github.com/VijayKumarGV/local-llm-studio/tree/main/desktop)
for signing + notarization.

## D. Optional observability stack

```sh
make obs-up             # Prometheus + Grafana + Tempo on localhost:3000
```

See [Monitoring](ops/monitoring.md) for what the dashboards show.

## Verifying the install

```sh
curl -fsS http://127.0.0.1:8080/api/health
```

Expected:

```json
{"status": "ok", "ollama": {"up": true, "models": 4}, ...}
```

If `ollama.up` is `false`, start Ollama (`brew services start ollama`)
and retry. If auth blocks you, the token is at
`docker compose exec studio cat /data/token` (Docker) or
`backend/token` (bare metal).
