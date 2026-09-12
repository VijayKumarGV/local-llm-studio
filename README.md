# Local LLM Studio

A **local-first, professional-grade LLM workspace** that fronts an
[Ollama](https://ollama.com) instance. Chat, retrieval over your own
documents, tool-using agents, artifacts, metrics, backups — all on your
machine, none of it in a browser tab you'll lose.

Built for Apple M4 Pro-class hardware (32B parameter models fit
comfortably in 37 GB unified memory); works on any machine Ollama runs
on.

<sub>Documentation: [avishwakarma.github.io/local-llm-studio](https://avishwakarma.github.io/local-llm-studio/)
· Changelog: [`CHANGELOG.md`](CHANGELOG.md) · Privacy:
[`PRIVACY.md`](PRIVACY.md) · License: Apache-2.0</sub>

---

## Why

Public chat apps are polished but leaky and censored. Cloud APIs
solve the intelligence problem but hand ownership of your
conversation to a third party. Running Ollama from a terminal solves
the ownership problem but is missing the parts that make an
assistant actually useful at work: retrieval over your own docs,
multi-model routing, tool calls, an artifact drawer, feedback
capture, metrics, backups.

Local LLM Studio is that glue — a first-class workspace UI backed by
a small typed Python service that composes those pieces into a tool
you'd actually reach for.

## What you get

- **Chat** with any Ollama model. Auto-routing by query length +
  vision attachment. Streaming with per-token TPS readout.
- **Expert workspaces** — curated Security + Coding presets with
  system prompts, RAG-indexed reference corpora, sensible model
  defaults.
- **Hybrid retrieval** — FTS5 BM25 + `nomic-embed-text` cosine fused
  via Reciprocal Rank Fusion, with optional HyDE + LLM rerank + MMR.
- **Tool loop** — search, execute Python in a Docker / sandbox-exec
  box, read + list workspace files, create artifacts. Every tool
  call streams as an SSE event the UI renders live.
- **Layered security** — Docker-first Python execution
  (`--network=none --read-only --cap-drop=ALL`), falling back to
  macOS `sandbox-exec`; unsandboxed only with explicit opt-in.
- **Observability** — Prometheus `/metrics`, opt-in OpenTelemetry
  tracing, five provisioned Grafana dashboards, four alert rules.
- **First-run wizard** — pulls required models, curates the corpus,
  provisions expert workspaces, all with live progress bars.
- **Voice I/O** — mic input via whisper.cpp; 🔊 replies via piper.
  Both hide themselves when the binary isn't installed.
- **Ships as a `.app`** — PyInstaller bundle + menu-bar tray + ⌥⌘Space
  hotkey, plus a Docker Compose distribution.
- **Evals** — deterministic JSONL spec harness, `--compare-baseline`
  gates on regression. 15 seed items for Security, 10 for Coding.

## Quickstart

Two supported paths — pick one.

### Docker (recommended)

```sh
git clone https://github.com/avishwakarma/local-llm-studio.git
cd local-llm-studio
docker compose up -d
./scripts/first_run.sh        # pulls models, corpus, workspaces
open http://127.0.0.1:8080
```

Grab the auth token:

```sh
docker compose exec studio cat /data/token
```

Paste it at `http://127.0.0.1:8080/auth?token=<token>` once, then the
cookie carries you.

### Bare metal (dev)

```sh
git clone https://github.com/avishwakarma/local-llm-studio.git
cd local-llm-studio
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
ollama serve &                # in one shell
make dev                      # in another
```

Auth token appears in the log line
`[auth] first-run token generated at …`.

See [`QUICKSTART.md`](QUICKSTART.md) for the fastest path or
[`docs/install.md`](docs/install.md) for the full matrix (bare metal /
Docker / macOS `.app` / observability stack).

## What it looks like

- Left rail: workspaces + conversation list.
- Middle: composer + streaming chat with citations + artifacts inline.
- Right (on demand): artifact drawer for code/files the model produced.
- Menu-bar tray (`.app` bundle): live status + ⌥⌘Space to summon the
  studio in your browser.

## Development

The public playbook we built this to is in
[`Plan/PROFESSIONAL_90DAY_PLAYBOOK.md`](Plan/PROFESSIONAL_90DAY_PLAYBOOK.md).
Twelve weeks, one deliverable per day, from proof-of-concept to
shippable v1.0.

Setup + commit + PR flow in [`CONTRIBUTING.md`](CONTRIBUTING.md).

```sh
make test              # 379 unit tests, <5s
make cov               # ~65% coverage on backend/
make lint              # ruff check
make typecheck         # mypy strict-ish
make evals             # against a running server, needs SESSION_TOKEN
make obs-up            # Prometheus + Grafana + Tempo on :3000
```

## Community

- Bugs / feature requests → GitHub issues.
- Security issues → **not** an issue. See
  [`SECURITY.md`](SECURITY.md).
- Code of conduct: [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) —
  Contributor Covenant 2.1.

## License

[Apache 2.0](LICENSE). Corpus content downloaded on first run keeps
its upstream licenses — see [`NOTICE.md`](NOTICE.md) for the full
attribution and the CC-BY-SA distribution note.
