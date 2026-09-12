# Monitoring

The studio ships a full local observability stack (Prometheus + Grafana
+ Tempo) as a *separate* compose file, so operators who just want to
chat don't pay for a metrics pipeline they aren't using.

## Bring it up

```sh
make obs-up
open http://localhost:3000     # admin / admin (change on first login)
```

Runs three services, all bound to `127.0.0.1`:

| Service    | Port | Purpose                                    |
| ---------- | ---- | ------------------------------------------ |
| Prometheus | 9090 | Scrapes `host.docker.internal:8080/metrics`|
| Grafana    | 3000 | Dashboards + alerts UI                     |
| Tempo      | 4318 | OTLP-HTTP trace receiver                   |

## Dashboards

Five checked-in dashboards live under `docker/grafana/dashboards/`. All
are `allowUiUpdates: true` — tweak in the UI, then
**Share → Export → Save to file** to promote the change back into git.

- **Overview** — active streams, req/s, success rate, HTTP
  p50/p95/p99, chat status split.
- **RAG** — retrieval latency, throughput, hit-count heatmap,
  empty-hit share.
- **Models & Tokens** — chat req/s by model, prompt/completion TPS by
  model, tool call trends.
- **Feedback** — 👍/👎 counters, 👎 share of ratings, coverage,
  event rate.
- **Alerts** — live `ALERTS` table + firing count over time.

## Metric catalog

Every custom metric is prefixed `studio_`:

| Metric                              | Type      | Labels             |
| ----------------------------------- | --------- | ------------------ |
| `studio_chat_requests_total`        | Counter   | `model`, `status`  |
| `studio_active_streams`             | Gauge     | —                  |
| `studio_ollama_up`                  | Gauge     | —                  |
| `studio_retrieval_latency_seconds`  | Histogram | —                  |
| `studio_retrieval_hits`             | Histogram | —                  |
| `studio_tool_calls_total`           | Counter   | `tool`, `status`   |
| `studio_feedback_total`             | Counter   | `rating`           |
| `studio_tokens_total`               | Counter   | `model`, `kind`    |

The base HTTP request timings (`http_requests_total`,
`http_request_duration_seconds_*`) come from
`prometheus-fastapi-instrumentator` and are already labelled by
method + handler + status.

## Alerts

Four rules in `docker/rules.yml`. Fires visible in the Prometheus UI
(`http://localhost:9090/alerts`) and the *Studio · Alerts* dashboard.

| Alert                          | Trip condition                             | Severity |
| ------------------------------ | ------------------------------------------ | -------- |
| `StudioHighErrorRate`          | 5xx rate > 5% for 5m                       | warning  |
| `StudioHighLatencyP95`         | HTTP p95 > 30s for 5m                      | warning  |
| `StudioOllamaDown`             | `studio_ollama_up == 0` for 90s            | critical |
| `StudioNegativeFeedbackSpike`  | 👎 share > 40% over 30m, with ≥ 20 ratings | warning  |

**Routing to Slack / macOS / email**: add an Alertmanager container
alongside Prometheus and point Prometheus's
`--alertmanager.notifier.url` at it. Keep the webhook URL in
`docker/.env` (not committed).

## Tracing

Opt-in per process. Point the studio at Tempo:

```sh
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make dev
```

Spans:

- Every HTTP request (via `FastAPIInstrumentor`).
- `rag.retrieve` — attributes: `rag.top_k`, `rag.project_id`,
  `rag.hits`.

Search in **Grafana → Explore → Tempo → Service `local-llm-studio`**.

## Cost ledger

The `cost_ledger` SQLite table records one row per completion with
`prompt_tokens` / `completion_tokens`. Aggregate via
`GET /api/cost/summary?group_by={model|project|day}[&since=ISO]`. Local
models don't have $-costs; this is a compute-usage proxy for spotting
runaway consumers.

## Feedback digest

Weekly rollup of thumbs-down feedback:

```sh
make feedback-digest        # → evals/digests/<ISO-week>.md
```

Groups by workspace, by model, extracts non-stopword token themes from
the downvoted prompts. Read-only DB access via URI mode.
