# docker/ — observability stack

Prometheus + Grafana + Tempo, provisioned with four studio dashboards.
Runs *alongside* the main studio stack (kept in a separate compose file
so users who just want to chat don't have to boot a metrics pipeline).

## Bring it up

```sh
# start the studio itself (existing compose stack) or `make dev`
make obs-up            # or:  docker compose -f docker/observability-compose.yml up -d
open http://localhost:3000    # admin / admin  (Grafana prompts on first login)
```

Optional tracing:

```sh
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 make dev
```

Then in Grafana Explore → Tempo, search by service `local-llm-studio`.

## Layout

- `observability-compose.yml` — the three services + named volumes.
- `prometheus.yml` — scrape config; targets `host.docker.internal:8080/metrics`.
- `tempo.yml` — OTLP-HTTP receiver on 4318, local file backend.
- `grafana/provisioning/datasources/` — auto-registers Prometheus + Tempo.
- `grafana/provisioning/dashboards/` — provider that reads `grafana/dashboards/*.json`.
- `grafana/dashboards/` — the four checked-in dashboards:
  - `overview.json` — active streams, HTTP req/s, error rate, p50/p95/p99 latency, chat status split
  - `rag.json` — retrieval latency, throughput, hit-count heatmap, empty-hit share
  - `models.json` — chat req/s by model, prompt/completion tokens per second, tool-call trends
  - `feedback.json` — 👍/👎 counters, 👎 share, coverage, feedback rate over time

Dashboards are `allowUiUpdates: true` — you can tweak in Grafana and
re-save. To promote a UI-edited dashboard into git, export its JSON
from Grafana (Share → Export → Save to file) and overwrite the file.

## Ports

| Service    | Container port | Host bind         |
| ---------- | -------------: | ----------------- |
| Prometheus |           9090 | 127.0.0.1:9090    |
| Grafana    |           3000 | 127.0.0.1:3000    |
| Tempo OTLP |           4318 | 127.0.0.1:4318    |
| Tempo API  |           3200 | 127.0.0.1:3200    |

All bound to localhost only. Flip to `0.0.0.0:` if you deliberately want
LAN access.

## Alerting

`rules.yml` defines four Prometheus alert rules — visible in
Prometheus (`http://localhost:9090/alerts`) and the *Studio · Alerts*
dashboard in Grafana:

| Alert                          | Condition                                                         | Severity   |
| ------------------------------ | ----------------------------------------------------------------- | ---------- |
| `StudioHighErrorRate`          | 5xx rate > 5% for 5m                                              | warning    |
| `StudioHighLatencyP95`         | p95 HTTP latency > 30s for 5m                                     | warning    |
| `StudioOllamaDown`             | `studio_ollama_up == 0` for 90s (from `/api/health`)              | critical   |
| `StudioNegativeFeedbackSpike`  | 👎 share > 40% over 30m, with ≥20 total ratings                   | warning    |

**Routing.** By default the stack has no Alertmanager container — alerts
just fire in-place. To route to Slack / email / macOS notifications,
add an Alertmanager service alongside Prometheus and set Prometheus's
`--alertmanager.notifier.url`. A minimal Slack-webhook Alertmanager
config lives in Grafana's docs. Keep the webhook URL in
`docker/.env` (not committed) and reference it as
`${SLACK_WEBHOOK_URL}` in the receiver config.

Editing the rules: bump the file in `docker/rules.yml`, then
`make obs-down && make obs-up` (Prometheus doesn't hot-reload the rule
file without a SIGHUP; the compose-down/up cycle is the simplest reset).
