# API

The full OpenAPI spec lives at `/openapi.json` (or Swagger UI at
`/docs`). This page highlights the endpoints most operators touch.

All non-public endpoints require the session bearer token, either as
the `studio_token` cookie or as `Authorization: Bearer <token>`.

Public (unauthenticated): `/`, `/auth`, `/api/health`, `/metrics`,
`/static/*`, `/favicon`.

## Health + onboarding

`GET /api/health` → `{status, ollama, rag, db_path}`. Also updates the
`studio_ollama_up` Prometheus gauge.

`GET /api/onboarding/status` → detection JSON:

```json
{
  "ollama_up": true,
  "models_installed": ["qwen2.5:32b", "nomic-embed-text"],
  "recommended_missing": ["qwen2.5-coder:32b"],
  "workspaces_created": 2,
  "corpus_downloaded": true,
  "auth_bootstrapped": true,
  "needs_setup": false
}
```

## Chat

`POST /api/chat/stream` — SSE endpoint driven by the agent orchestrator.

Body:

```json
{
  "conversation_id": "…",
  "message": "…",
  "model": "qwen2.5:32b",
  "enable_web_search": false,
  "enable_code_execution": false,
  "think_deeply": false,
  "attachments": []
}
```

Events emitted (all `event: <name>\ndata: <json>\n\n`):

| event              | payload                                                |
| ------------------ | ------------------------------------------------------ |
| `model_selected`   | `{requested, chosen, reason}`                          |
| `execution_start`  | `{execution_id, model}`                                |
| `prompt_warning`   | `{findings}` — heuristic prompt-injection scanner      |
| `retrieval_debug`  | `{query, hits}`                                        |
| `citation`         | `{id, filename, snippet, …}`                           |
| `memory_recalled`  | `{count, facts}`                                       |
| `plan_step`        | `{step, action}`                                       |
| `tool_start`       | `{tool, title, ...args}`                               |
| `tool_end`         | `{tool, status, result}`                               |
| `tool_denied`      | `{tool, reason}`                                       |
| `token`            | `{delta}`                                              |
| `thinking_phase`   | `{phase, iteration}` — deep-think reviewer loop        |
| `done`             | `{message_id, content, token_count, eval_tps, tool_calls, citations, artifacts}` |
| `cancelled`        | `{message}`                                            |
| `error`            | `{error, ...}`                                         |

## RAG

`GET /api/rag/query?q=…&project_id=…&top_k=6` — debug retrieval;
returns ranked hits without generating a chat response.

## Feedback

`POST /api/feedback {message_id, rating, note}` — rating ∈ `-1|0|1`.
0 clears prior rating. Increments the `studio_feedback_total`
Prometheus counter.

`GET /api/feedback?message_id=…` or `?conversation_id=…` — read.

## Cost / token ledger

`GET /api/cost/summary?group_by={model|project|day}[&since=ISO]` —
aggregate the `cost_ledger` table.

## Models

`GET /api/models` — enriched Ollama tag list with capability metadata.

`POST /api/models/pull {model}` — SSE stream of Ollama's `pull`
progress. Consumed by the wizard's per-model progress bars.

## Sandbox

`POST /api/sandbox/run {code, timeout}` — runs `code` in the strongest
sandbox available. Response includes `status`, `stdout`, `stderr`,
`return_code`, `sandboxed`, `sandbox_kind`.

## Audit

`GET /api/audit?limit=100[&action=…][&resource_type=…]` — read-only
view of the append-only audit trail.

## Metrics

`GET /metrics` — Prometheus exposition (public path so a local scraper
doesn't need auth). See [Monitoring](ops/monitoring.md).
