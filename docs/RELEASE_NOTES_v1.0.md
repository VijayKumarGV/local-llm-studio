# Release notes — v1.0.0

**Local LLM Studio v1.0** is the first stable release. It turns a
working Ollama daemon into a full workspace: chat, retrieval over
your own documents, tool-using agents, artifacts, metrics, backups,
first-run wizard, and a native macOS `.app` bundle — all on your
machine, none of it in a browser tab you'll lose.

## The 30-second pitch

Public chat apps are polished but leaky and censored. Cloud APIs
solve the intelligence problem but hand ownership of your
conversation to a third party. Running Ollama from a terminal solves
the ownership problem but is missing the parts that make an
assistant actually useful at work. Local LLM Studio is that glue — a
first-class workspace UI backed by a small typed Python service that
composes those pieces into a tool you'd actually reach for.

## What's in the box

- Chat with any Ollama model, streaming, with per-token TPS readout.
- Two curated **expert workspaces** (Security + Coding) with system
  prompts and RAG-indexed reference corpora.
- **Hybrid RAG** — FTS5 BM25 + `nomic-embed-text` cosine, RRF-fused,
  optional HyDE + LLM rerank + MMR.
- **Tool loop** — search, execute Python (Docker sandbox by default,
  macOS `sandbox-exec` fallback), read + list workspace files,
  create artifacts. Every call streams live via SSE.
- **First-run wizard** with per-model download progress bars.
- **Recovery banners** for ollama-down / embed-missing / upload
  retries.
- **Voice** — mic input via whisper.cpp, spoken replies via piper,
  both gated behind a `/api/audio/status` capability probe so the
  buttons hide themselves when the binaries aren't installed.
- **Observability stack** — Prometheus + Grafana + Tempo in one
  compose file, five provisioned dashboards, four alert rules.
- **Ships two ways** — Docker Compose or a native macOS `.app` with a
  menu-bar tray + ⌥⌘Space global hotkey.
- **Evals** — deterministic JSONL spec harness with regression gate.

## Highlights of the 12-week build

- **Security first** — layered sandbox with runtime preflight,
  path-traversal fix on file uploads, prompt-injection heuristic
  scanner, sensitive settings routed to macOS Keychain, append-only
  audit log, CSP + hardening headers on every response.
- **Ops-ready** — 5-dashboard Grafana stack with alert rules for 5xx
  rate, p95 latency, ollama-down, and negative-feedback spikes;
  nightly SQLite backup with monthly restore drill in the docs.
- **Regression discipline** — 379 unit tests, ~65% coverage, mypy
  strict-ish, ruff, e2e smoke suite in Playwright, an eval harness
  that gates on any pass→fail on a fixed spec set.
- **Documented** — MkDocs Material site with 9 pages, deployed on
  every push to `docs/`.
- **Legal + policy done** — LICENSE (Apache-2.0), NOTICE with corpus
  license attribution, PRIVACY with a per-endpoint table of what
  leaves the machine, Contributor Covenant CoC.

## Compatibility

- **Runtime**: Python 3.12, Ollama (latest), Docker Compose ≥ 2, or
  bare metal.
- **Hardware**: any machine Ollama runs on. Comfortable on Apple M4
  Pro with 32 GB+ unified memory for 32B-class models; smaller boxes
  are fine with smaller models (`llama3.2:3b`, `qwen2.5:7b`).
- **Data**: single SQLite file at `backend/workspace.db` or
  `/data/workspace.db` (Docker). Fully portable — copy the file to a
  new machine.

## Upgrading from a pre-1.0 tag

- The DB schema is forward-migrated by `yoyo` at startup. Snapshot
  first via `make backup` — no rollback path except restoring from
  that snapshot.
- The observability stack is a *separate* compose file
  (`docker/observability-compose.yml`) — no impact on the main
  studio unless you `make obs-up`.
- Voice endpoints (`/api/audio/*`) are new; the frontend hides the
  buttons when whisper / piper aren't present.

Full CHANGELOG entry:
[`CHANGELOG.md`](https://github.com/VijayKumarGV/local-llm-studio/blob/main/CHANGELOG.md).

## Deferred

- Automated Alertmanager wiring — `docker/rules.yml` defines four
  alert rules but there's no built-in Slack / email routing. Add an
  Alertmanager container and point Prometheus's
  `--alertmanager.notifier.url` at it.
- Multi-user mode — v1 is deliberately single-user with a shared
  session token. Post-v1 fork "B" (Postgres + auth + RBAC) is on the
  roadmap; see the tail of `Plan/PROFESSIONAL_90DAY_PLAYBOOK.md`.
- Notarization automation only runs when the Apple secrets are
  configured. Unsigned `.app.zip` still uploads to the release for
  local inspection.

## Where to file feedback

- Bugs / feature requests → GitHub Issues.
- Security → [`SECURITY.md`](https://github.com/VijayKumarGV/local-llm-studio/blob/main/SECURITY.md). Do not open a public
  issue.
- Docs typo? PR against `docs/*.md` — CI enforces
  `mkdocs build --strict`.

Thanks to everyone who dogfooded the RC.
