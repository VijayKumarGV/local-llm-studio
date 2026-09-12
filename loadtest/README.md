# Load tests

Thin [k6](https://k6.io/) scripts that exercise the studio's three
hot paths under load: `/api/health`, `/api/rag/query`,
`/api/sandbox/run`. Chat-stream load is deliberately not scripted —
tokens-per-second is dominated by the model backend, not the studio.

## Install

```sh
brew install k6      # macOS
# or:  https://k6.io/docs/get-started/installation/
```

## Run

Start the server + corpus first (or bring the docker stack up), then
export the session token so k6 can hit authed endpoints:

```sh
export SESSION_TOKEN=$(docker compose exec studio cat /data/token)   # or:  cat backend/token
k6 run loadtest/health.js
```

Env overrides:

- `STUDIO_URL` — default `http://127.0.0.1:8080`
- `SESSION_TOKEN` — required for `/api/rag/query` and `/api/sandbox/run`

## What "good" looks like

Baseline targets (M4 Pro 37 GB, warm caches, warm docker image):

| Scenario | Assertion         | Rationale                                   |
| -------- | ----------------- | ------------------------------------------- |
| health   | p95 < 50 ms       | Just an in-process JSON handler + Ollama ping. Anything higher means GIL contention or logging. |
| rag      | p95 < 500 ms      | Includes optional HyDE + LLM rerank; with defaults these add ~250 ms cumulative. |
| sandbox  | p95 < 3 s         | Docker cold-start is 1.5–2 s. Warm reuse via `docker run` is fine — no daemon-side caching yet. |
| any      | error rate < 1%   | 1% covers occasional Ollama timeouts under heavy concurrent load. |

`k6 run` fails with a non-zero exit code if any threshold trips, so this
doubles as a regression gate you can wire into CI (see
`.github/workflows/loadtest.yml` — currently workflow_dispatch-only
because a warm docker container takes ~10 s to spin up on GitHub
runners).

## Interpreting the histogram

k6 prints `studio_<name>_ms` trends with min/med/p90/p95/max. If p95
regresses:

- **health**: check `active_streams` — if there are >0 streams during the
  ramp, the GIL contention with the SSE writer is your bottleneck.
- **rag**: turn HyDE off (`{"use_hyde": false}`) and re-run; if p95
  drops, the small-model latency dominates. Consider a smaller HyDE
  model or disabling HyDE for the sub-100-char query class.
- **sandbox**: check Docker's `stats` — memory limit hits push
  invocations into swap. Widen `--memory` or move to sandbox-exec on
  macOS.

## Not covered

- **Chat stream throughput** — bottlenecked by Ollama, not us. Measure
  with a single-VU stream and eyeball the `token/s` metric from
  `event: done`.
- **Long-running work in tools** — none of our tools are supposed to
  block for >5 s; if one does the sandbox already timeouts it.
