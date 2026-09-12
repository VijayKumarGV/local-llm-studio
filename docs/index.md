# Local LLM Studio

A FastAPI + single-page-app **local-first LLM workspace** that fronts a
running [Ollama](https://ollama.com/) instance. Designed to give an
experienced operator a *professional-grade* private AI environment on an
Apple M4 Pro (or any similarly-capable machine) — no cloud calls, no
telemetry, no subscriptions.

## Why this exists

Public chat interfaces are polished but leaky, deliberately censored,
and impose usage limits. Cloud APIs solve the intelligence problem but
give up ownership of the conversation. Running Ollama from a terminal
solves the ownership problem but is missing everything that makes an
assistant actually usable at work: retrieval over your own documents,
multi-model routing, tool calls, an artifact drawer, feedback capture,
metrics, backups.

Local LLM Studio is the glue: a first-class workspace UI, backed by a
small typed Python service, that composes those pieces into a tool you
would actually reach for.

## Feature summary

- **Chat** with any Ollama-loadable model. Auto-routing by query length +
  vision attachment. Streaming responses with per-token TPS readout.
- **Expert workspaces** — curated Security + Coding presets with system
  prompts and RAG-indexed reference corpora.
- **Hybrid retrieval** — FTS5 BM25 + `nomic-embed-text` cosine, fused
  via Reciprocal Rank Fusion. Optional HyDE query rewriting + LLM
  reranker + MMR diversification.
- **Tool loop** — search, execute Python in a Docker/sandbox-exec box,
  read files, list files, create artifacts. Every tool call is emitted
  as an SSE event the UI renders live.
- **Layered security** — Docker-first Python execution with cap-drop=ALL
  / read-only rootfs / --network=none, falling back to macOS
  `sandbox-exec` when Docker isn't available, unsandboxed **only** when
  explicitly opted in.
- **Observability** — Prometheus `/metrics`, OpenTelemetry tracing, a
  provisioned Grafana stack with five dashboards + four alert rules.
- **Ships as a `.app`** — PyInstaller bundle + menu-bar tray + global
  ⌥⌘Space hotkey, plus a Docker Compose distribution.
- **Evals** — deterministic JSONL spec harness with retrieval-hit and
  answer must-contain / must-not-contain checks; regression-gates on CI.

## Where to next

- [Install](install.md) — Docker or bare metal.
- [First run](first-run.md) — bootstrap the wizard.
- [Concepts](concepts.md) — what the moving pieces are.
- [Architecture](architecture.md) — how they fit together.
- [API](api.md) — endpoint reference.
- [Monitoring](ops/monitoring.md) — dashboards + alerts.
