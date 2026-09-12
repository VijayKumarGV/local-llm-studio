# Quickstart

The shortest working path. For the full install matrix (bare metal,
`.app` bundle, observability stack) see
[`docs/install.md`](docs/install.md).

## Prerequisites

- macOS or Linux
- 16 GB RAM (32 GB+ for 32B-class models)
- Docker Desktop *or* Python 3.12

## Docker (fastest)

```sh
git clone https://github.com/VijayKumarGV/local-llm-studio.git
cd local-llm-studio
docker compose up -d
./scripts/first_run.sh
```

`first_run.sh` pulls the recommended models (~40 GB total; safe to
re-run to resume interrupted downloads), curates the reference corpus
into `corpus/`, and provisions the two expert workspaces.

Then:

```sh
docker compose exec studio cat /data/token
# → paste it once at http://127.0.0.1:8080/auth?token=<token>
open http://127.0.0.1:8080
```

That's it. First-run wizard will confirm the setup and offer a
one-click upgrade if any recommended model is still missing.

## Bare metal (dev)

```sh
git clone https://github.com/VijayKumarGV/local-llm-studio.git
cd local-llm-studio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Terminal 1
ollama serve

# Terminal 2
make dev
```

Watch the log for `[auth] first-run token generated at …` — that's
your session token. Same `/auth?token=…` handshake as above.

## Sanity check

```sh
curl -fsS http://127.0.0.1:8080/api/health
# → {"status":"ok","ollama":{"up":true,"models":N}, ...}
```

If `ollama.up` is `false`, run `brew services start ollama` (macOS) or
`ollama serve` in a spare terminal, then retry.

## Common next steps

- Attach a document to a conversation — drag it into the composer.
- Enable web search per-conversation (toolbar toggle).
- Bring up the observability stack:
  `make obs-up` → http://localhost:3000 (admin / admin).
- Run the built-in eval harness against your workspace:
  `make evals-security` or `make evals-coding`.
- Wipe everything (data lives on named docker volumes):
  `docker compose down -v`.

## Troubleshooting

| Symptom                                           | Try                                                                            |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| Red banner "Ollama is not reachable"              | `brew services start ollama` (or `ollama serve`), then click *Retry*.          |
| Amber banner "embed model not installed"          | Click *Pull now* in the banner — hits `/api/models/pull` with progress.        |
| /auth returns 401                                 | Token typo. Reprint with `docker compose exec studio cat /data/token`.         |
| First-run wizard doesn't appear                   | Already dismissed. Reopen from the empty-state link on the messages viewport. |
| Sandbox says "no backend available" on macOS      | Install Docker Desktop, or opt in with `STUDIO_ALLOW_UNSANDBOXED=1` (unsafe). |

More in [`docs/first-run.md`](docs/first-run.md).
