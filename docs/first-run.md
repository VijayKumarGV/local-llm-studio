# First run

When you first load the UI, `/api/onboarding/status` runs and — if
`needs_setup` is true — pops a five-step modal wizard. This page walks
through what each step does so you can drive the wizard confidently.

## Step 1 — Welcome

Shows a live status snapshot: is Ollama reachable, how many models are
installed, whether the two expert workspaces exist, whether the RAG
corpus is present. No actions here — this is the confirmation of what
the wizard is about to fix.

## Step 2 — Pick models

Recommended set (all optional except `nomic-embed-text`):

| Model                  | Size  | Purpose                                        |
| ---------------------- | ----- | ---------------------------------------------- |
| `nomic-embed-text`     | 0.3 GB | Embeddings for RAG. **Required** for retrieval. |
| `qwen2.5:32b`          | 19 GB  | General-purpose chat.                          |
| `qwen2.5-coder:32b`    | 19 GB  | Coding-tuned; Coding Expert default.           |
| `llama3.2:1b`          | 1.3 GB | Fast triage / routing / HyDE query rewrites.   |

Progress bars are live — the wizard consumes the SSE stream from
`POST /api/models/pull`, which forwards Ollama's NDJSON download
progress.

## Step 3 — Curate corpus

Downloads the reference corpora into `corpus/`:

- **Security** — OWASP cheatsheets + Top 10, ASVS, MITRE ATT&CK, common
  payloads (READMEs only).
- **Coding** — Rust book, CPython tutorial + howto, Effective Go, TS
  handbook.

All sources are permissively licensed (MIT / Apache 2.0 / CC-BY / PSF /
US-gov work). This step shells out to
`scripts/curate_corpus.py` — safe to re-run, skips already-cloned
sources.

## Step 4 — Build workspaces

Provisions `Security Expert` and `Coding Expert` projects, ingests the
corpora into their RAG indexes, sets default models. Runs
`scripts/build_expert_workspaces.py`. Idempotent.

## Step 5 — Done

Quick tips:

- `⌘K` — command palette
- `?` — full shortcut list
- Drop files into the composer to attach them
- 👍/👎 buttons on each response — used later for RAG weight tuning

You can re-launch the wizard any time from the empty-state link on
the main viewport.

## Fallbacks when Ollama is unreachable

If the wizard status shows `ollama_up: false`, a red banner appears
across the top with a "Retry" button and a hint to run
`brew services start ollama` or `ollama serve`. Fix the underlying
problem, click Retry, and re-run the wizard.

## Fallbacks when only the embed model is missing

An amber banner appears with a **Pull now** button that hits the same
streaming `/api/models/pull` endpoint. Faster than reopening the wizard
just for one model.
