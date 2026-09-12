# Concepts

The vocabulary you need to navigate the UI and the code.

## Workspace (Project)

A named container for related conversations. Ships two out of the box:
**Security Expert** and **Coding Expert**. Each has:

- A **system prompt** injected at the start of every conversation.
- A **default model** the router will pick unless a specific model is
  chosen.
- A **RAG index** populated from files ingested into that project.
- **Settings** — temperature, tool permissions, whether to auto-attach
  session notes.

Internally: a row in the `projects` table. Conversations reference a
`project_id`.

## Conversation

A linear list of `messages` with an optional `title`. Belongs to
exactly one workspace (or none — "unassigned"). Deleting a conversation
cascades to its messages, attachments, and feedback rows.

## Attachment

Any file the user drops on the composer or the workspace pane.
Attachments get:

- **Chunked** — header-aware markdown chunking with `~3200`-char
  targets and `~400`-char overlaps. Each chunk stores its enclosing
  heading so retrieval + citations know what section it came from.
- **Embedded** — one `nomic-embed-text` call per chunk. Vectors stored
  as float32 BLOBs.
- **FTS-indexed** — the chunk text also flows into an FTS5 virtual
  table for BM25 keyword search.

Two indexes, one retrieval — see [Hybrid RAG](#hybrid-rag).

## Hybrid RAG

Retrieval fuses two ranked lists via **Reciprocal Rank Fusion (RRF)**:

1. **Vector search** — cosine of the query embedding against every
   scoped chunk's embedding.
2. **BM25 keyword search** — SQLite FTS5's built-in ranking.

Then three optional quality upgrades (all default-on, all
per-workspace-toggleable in Settings):

- **HyDE** — a fast small model writes a plausible 2-3 sentence
  hypothetical answer; the query used for retrieval is the concatenation
  of the original + hypothetical. Catches paraphrase mismatches.
- **LLM rerank** — a fast small model scores the top-20 candidates 0–10
  for relevance and re-sorts.
- **MMR** — Maximal Marginal Relevance diversifies the final top-K so
  it isn't three near-duplicate chunks.

## Tool loop

The agent orchestrator runs a bounded loop:

1. Model responds with either text OR a tool-call (native
   function-calling — no XML).
2. If a tool call was requested and permitted, invoke it, append the
   result as a `tool` message, and re-invoke the model.
3. Loop until the model produces a plain text turn OR the iteration
   budget is exhausted.

Tools: `search_web`, `read_file`, `list_files`, `execute_python_code`,
`create_artifact`. Each has a permission level: `auto_allow`,
`require_approval`, or `disabled`. `execute_python_code` is
`require_approval` by default.

## Sandbox

Where `execute_python_code` runs:

| Backend         | When picked                              | Isolation                                          |
| --------------- | ---------------------------------------- | -------------------------------------------------- |
| Docker          | `docker` CLI + daemon reachable          | `--network=none --read-only --cap-drop=ALL`        |
| `sandbox-exec`  | macOS + `/usr/bin/sandbox-exec` + preflight passes | Deny-default profile; scratch dir carved out       |
| Unsandboxed     | `STUDIO_ALLOW_UNSANDBOXED=1` opt-in      | None. Warns on every run.                          |
| Unavailable     | Nothing above works                      | Endpoint returns an error explaining how to fix.   |

## Metrics + tracing

`/metrics` is a Prometheus scrape target. The custom counters cover
chat request outcomes, retrieval latency, tool call statuses, feedback,
and per-model token accounting. See [Monitoring](ops/monitoring.md).

OpenTelemetry tracing is off by default; set
`OTEL_EXPORTER_OTLP_ENDPOINT` and spans stream to your OTLP collector
(the shipped Tempo container is happy to receive them on
`localhost:4318`).

## Auth

Session-token bearer auth. On first server start a random token is
written to `/data/token` (Docker) or `backend/token` (bare metal). Set
the cookie by visiting `/auth?token=…` once.

## Audit log

Every state-changing endpoint appends a row to `audit_log`. Read via
`GET /api/audit`. Append-only; never raises upward — a logging failure
never breaks the response the user is waiting on.
