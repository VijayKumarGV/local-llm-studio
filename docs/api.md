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

## Voice I/O

`GET /api/audio/status` — reports `{transcribe: {available, reason}, tts: {available, reason}}`
so the frontend can hide the mic / 🔊 buttons when the binary or model
is missing.

`POST /api/audio/transcribe` — multipart upload; returns `{text}`.
503 with a machine-readable reason when whisper-cli / the model is
absent.

`POST /api/audio/tts` — JSON `{text}`; returns `audio/wav` bytes.
503 with the same fallback semantics as transcribe.

## Metrics

`GET /metrics` — Prometheus exposition (public path so a local scraper
doesn't need auth). See [Monitoring](ops/monitoring.md).

## Full endpoint index

The above sections cover the endpoints most operators touch. The full
set — auto-generated from FastAPI's `/openapi.json` — is:

| Method(s)                 | Path                                                     |
| ------------------------- | -------------------------------------------------------- |
| GET                       | `/api/health`                                            |
| GET                       | `/api/onboarding/status`                                 |
| GET                       | `/api/audio/status`                                      |
| POST                      | `/api/audio/transcribe`                                  |
| POST                      | `/api/audio/tts`                                         |
| GET / POST                | `/api/models`                                            |
| GET                       | `/api/models/capabilities`                               |
| POST                      | `/api/models/pull`                                       |
| GET / POST                | `/api/projects`                                          |
| GET / PATCH / DELETE      | `/api/projects/{project_id}`                             |
| GET                       | `/api/projects/{project_id}/files`                       |
| GET / POST                | `/api/conversations`                                     |
| GET / PATCH / DELETE      | `/api/conversations/{conv_id}`                           |
| POST                      | `/api/conversations/{conv_id}/branch`                    |
| POST                      | `/api/conversations/{conv_id}/duplicate`                 |
| PATCH / DELETE            | `/api/messages/{message_id}`                             |
| POST                      | `/api/chat/stream`                                       |
| POST                      | `/api/chat/compare`                                      |
| GET                       | `/api/rag/query`                                         |
| POST                      | `/api/files/upload`                                      |
| POST                      | `/api/files/from-url`                                    |
| DELETE                    | `/api/files/{file_id}`                                   |
| GET / POST / DELETE       | `/api/artifacts`                                         |
| GET / DELETE              | `/api/artifacts/{artifact_id}`                           |
| GET                       | `/api/artifacts/{artifact_id}/download`                  |
| GET / POST                | `/api/feedback`                                          |
| GET                       | `/api/cost/summary`                                      |
| GET                       | `/api/audit`                                             |
| GET / POST                | `/api/memory`                                            |
| DELETE                    | `/api/memory/{memory_id}`                                |
| POST                      | `/api/memory/extract`                                    |
| GET / PATCH               | `/api/settings`                                          |
| GET                       | `/api/search`                                            |
| POST                      | `/api/sandbox/run`                                       |
| POST                      | `/api/workspace/export`                                  |
| POST                      | `/api/workspace/import`                                  |
| GET                       | `/metrics`                                               |
| GET                       | `/auth?token=…`                                          |
