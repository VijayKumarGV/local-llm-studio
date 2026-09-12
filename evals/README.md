# Evals

Small, honest, regression-catching evaluation harness for the two expert
workspaces (Security + Coding). The philosophy:

> Track a fixed set of prompts we know how to grade automatically, run
> them against every meaningful change, and refuse to ship regressions.

We deliberately *don't* attempt LLM-as-judge scoring or full RAGAS —
those add cost and flakiness we don't need at this scale. Every check
here is a deterministic string / set membership test that a human can
audit and update.

## Spec format

Each spec file is [JSONL](https://jsonlines.org/) (one JSON object per
line). Fields:

| field                        | required | meaning                                                                    |
| ---------------------------- | :------: | -------------------------------------------------------------------------- |
| `id`                         | ✔        | Stable identifier (`sec-001`, `cod-001`, …) — used across history reports. |
| `query`                      | ✔        | The prompt sent to the chat endpoint verbatim.                             |
| `workspace`                  | ✔        | `security` or `coding` — routes the request to the matching project.       |
| `expected_sources`           |          | List of filename fragments (`substring` match, case-insensitive) that should appear in RAG top-K. |
| `answer_must_contain`        |          | List of substrings the answer MUST contain (case-insensitive).             |
| `answer_must_not_contain`    |          | List of substrings that MUST NOT appear (guards against hallucinations, jailbreaks, wrong claims). |
| `expected_technique_ids`     |          | For security items grounded in MITRE ATT&CK — list of technique IDs (`T1055`) the answer should mention. |
| `notes`                      |          | Human-readable comment. Ignored by the runner.                             |

At least one of `expected_sources`, `answer_must_contain`,
`answer_must_not_contain`, or `expected_technique_ids` MUST be present —
a spec without any check is meaningless.

## Metrics

For each spec the runner records:

- **retrieval_hit** — did ANY `expected_sources` fragment match ANY file
  returned by `/api/rag/query` (top-K, K=6 by default)?
- **must_contain_hit** — did EVERY `answer_must_contain` string appear
  in the streamed answer?
- **must_not_contain_avoided** — did the answer avoid EVERY
  `answer_must_not_contain` string?
- **technique_ids_hit** — for MITRE-grounded items, did the answer
  mention every `expected_technique_ids` entry?

Aggregated to a report:

```json
{
  "generated_at": "2026-09-12T14:33:12Z",
  "spec_file": "evals/security_expert.jsonl",
  "server": "http://127.0.0.1:8080",
  "model": "qwen2.5:32b",
  "counts": {"total": 15, "pass": 13, "fail": 2},
  "pass_rate": 0.867,
  "regressions_vs_baseline": [{"id": "sec-004", "was": true, "now": false}],
  "results": [
    {"id": "sec-001", "retrieval_hit": true, "must_contain_hit": true, "must_not_contain_avoided": true, "pass": true},
    ...
  ]
}
```

Reports drop into `evals/history/<UTC-ISO8601>.json`; a symlink
`evals/history/latest.json` always points at the newest.

## Running

```sh
# start the server + ollama first (docker compose up -d, or make dev)
.venv/bin/python evals/run.py \
  --spec evals/security_expert.jsonl \
  --server http://127.0.0.1:8080 \
  --project-id <security-workspace-id>

# regression-gate mode: exit nonzero if pass_rate dropped >2pp from the
# last report on disk
.venv/bin/python evals/run.py --spec evals/coding_expert.jsonl --compare-baseline
```

`--project-id` defaults to auto-detect (the runner enumerates
`/api/projects` and matches on the `workspace` field of the spec set).

## Growing the set

Add a line to the relevant `.jsonl`. Keep items narrow (one topic each),
prefer factual questions to open-ended ones, prefer substring checks
you'd stake your job on ("`parameterized`" — yes) over
opinion-dependent phrasing ("clean" — no).

Every item you add is a permanent invariant — think twice before
deleting one. If a check goes stale, prefer *updating* the expected
value in a PR that explains why the ground truth moved, not silent
deletion.
