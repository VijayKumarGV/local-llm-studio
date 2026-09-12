# Architecture

Small mental model first, then a per-module tour.

## Big picture

```
┌────────────────────────────────────────────────────┐
│                  Browser (SPA)                     │
│  static/js/{app,onboarding,keybindings,recovery,   │
│             agent_ui,artifacts_ui,markdown,...}    │
└──────────────┬─────────────────────────────────────┘
               │ fetch + SSE (cookie-authed)
               ▼
┌────────────────────────────────────────────────────┐
│              FastAPI (backend/server.py)           │
│  middleware chain:                                 │
│    request_context → auth → security_headers      │
│  metrics.instrument() mounts /metrics              │
│  tracing.setup() opt-in via OTEL_..._ENDPOINT     │
└──┬──────────┬──────────┬──────────┬────────────────┘
   │          │          │          │
   ▼          ▼          ▼          ▼
 agent      rag       tools      cost_ledger
 orches-    (hybrid   (search,   feedback
 trator     RRF)      exec,      audit_log
                      artifacts) prompts
                                 secure_settings
   │          │          │          │
   ▼          ▼          ▼          ▼
        SQLite (workspace.db)  +  Ollama HTTP
```

## Middleware ordering

Order is *inside-out* — last registered is outermost. We want:

1. `security_headers_middleware` (outermost) — decorates every response,
   including 401s from auth, with CSP + X-Frame-Options +
   Referrer-Policy + Permissions-Policy.
2. `auth_middleware` (middle) — bearer/cookie check. 401s bubble up
   through security so responses stay hardened.
3. `request_context_middleware` (innermost) — sets a request-scoped
   `contextvar` used by the logging filter.

## Data model

```
projects ── conversations ── messages
                                  ├── attachments (files) ── file_chunks
                                  ├── artifacts
                                  ├── citations
                                  ├── message_feedback
                                  └── cost_ledger
```

Every stateful table lives in a single SQLite DB (`workspace.db`).
Migrations are yoyo-managed; the server applies pending migrations at
startup.

## Retrieval pipeline

`backend/rag.py::retrieve` is a thin wrapper around `_retrieve_impl`
that adds metrics + tracing. `_retrieve_impl` runs:

1. Query embed (`_embed_batch`), optionally HyDE-augmented.
2. Vector candidates — cosine top-N against scoped chunks.
3. BM25 candidates — FTS5 `MATCH` against the same scope.
4. RRF fuse the two.
5. Optional LLM rerank of the top-20.
6. Optional MMR diversification for the final top-K.

Every stage is toggleable via settings — defaults are all-on.

## Streaming chat

`stream_chat` returns a `StreamingResponse` wrapping
`_instrumented_stream`, which wraps `orchestrator.run_agent_loop`. The
orchestrator emits `event: <name>` SSE frames as it works; the wrapper
counts the active-streams gauge, records the terminal status by
labelled model, and sniffs `tool_end`/`tool_denied` frames to update
the tool-calls counter.

## Sandboxes

`backend/security.py` layers three backends. `_sandbox_kind()` picks
one per call so switching Docker on/off doesn't require a restart. The
sandbox-exec path preflights with a trivial profile once (cached), so
hardened macOS hosts where the syscall is denied degrade to
`unavailable` cleanly rather than reporting every user program as an
error.

## Observability wiring

- `backend/metrics.py` — `prometheus_client` counters/histograms +
  `prometheus_fastapi_instrumentator` for base HTTP timings. Endpoint
  mounted at `/metrics`.
- `backend/tracing.py` — no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is
  set. When enabled, `FastAPIInstrumentor` auto-spans every request +
  we add manual spans in `rag.retrieve`.
- `backend/cost_ledger.py` — one row per completion with prompt +
  completion token counts. `GET /api/cost/summary` aggregates.

## Ship targets

- Bare metal: `.venv/bin/uvicorn backend.server:app`.
- Docker: `docker compose up -d` — two services (Ollama + studio),
  localhost-only ports, named volumes for durability.
- macOS `.app`: `make bundle` — PyInstaller-frozen tray app that spawns
  uvicorn as a subprocess and routes user data to
  `~/Library/Application Support/LocalLLMStudio/`.
