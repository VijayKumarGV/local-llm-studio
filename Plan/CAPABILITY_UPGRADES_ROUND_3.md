# Capability Upgrades — Round 3

Analysis of what the app can be next, based on the actual current state (surveyed 2026-09-12).

Progress key: `[ ]` pending · `[~]` in progress · `[x]` completed

---

## Current baseline (what's already in)

| Layer | State |
|---|---|
| Models | qwen2.5:32b · qwen2.5-coder:32b · dolphin3 · deepseek-r1:14b (reasoning) · nomic-embed-text · llama3.2:1b — 6 models, ~53 GB |
| Backend | ~3.6k LOC · async httpx · native Ollama tool calling · multi-step agent loop · macOS sandbox-exec for Python · hybrid RAG (FTS5 BM25 + vector, RRF) · header-aware chunks · think-deeply (draft→critique→revise) · long-term memory · yoyo migrations · structured logging · /api/health |
| Data | 5,758 RAG chunks · 2,716 corpus files · SQLite 67 MB · FTS5 keyword index |
| Workspaces | 🛡️ Security Expert (OWASP+MITRE+CWE) · 💻 Coding Expert (Rust+Python+Go+TS) + 2 audit test projects still hanging around |
| Frontend | Vanilla ESM · marked + highlight.js + DOMPurify · think-block folding · collapsible workspace files · capability badges · message actions (edit/branch/regenerate) |

## What's realistically missing (ranked by user-visible smartness / hour)

### Tier 1 — biggest bang, small effort

- [x] **HyDE query expansion.** Before retrieval, ask the model to write a *hypothetical answer* to the user's question. Embed that instead of the raw question. Documents that actually contain the answer end up much closer in vector space. ~30 lines in `rag.py`. Zero UI change.

- [x] **LLM reranker on top-N.** After hybrid retrieval returns top-30, feed short snippets to `dolphin3` (fast 8B) with the query, ask "which are most relevant?", keep top-K. Kills junk chunks. ~50 lines. Adds ~1s latency; make it opt-in per project via a setting.

- [x] **MMR diversity in top-K.** Current retrieval routinely returns 4 chunks from the same file for a common query — Maximal Marginal Relevance re-orders so top-K spans distinct sources. Small change to `rag.retrieve`.

- [x] **Model router.** Cheap heuristic + settings map: reasoning-flag keywords (why, prove, analyze, compare, design) → deepseek-r1; code keywords in Coding Expert → qwen2.5-coder; ultra-short questions → llama3.2:1b. Per-workspace override already exists. ~40 lines in orchestrator.

- [x] **Iterative Think-Deeply.** Current: 1 critique + 1 revise. Better: loop up to N iterations, stop when reviewer says "no issues." Bounded by max_iters (default 3). ~30 line change in orchestrator.

### Tier 2 — new input modalities

- [x] **PDF ingestion.** Added `backend/extractors.py` with `pypdf`-based text extraction; `/api/files/upload` now detects PDFs and chunks their text. Skips image-only PDFs gracefully.

- [x] **Web page ingestion.** New endpoint `POST /api/files/from-url` — fetches via httpx, strips nav/ads with `trafilatura`, saves as `.md`, ingests into RAG. Verified on RFC 8446 (314 KB → 114 chunks).

- [x] **Vision model.** Pulled `minicpm-v` (~4.4 GB, strong OCR). Orchestrator base64-encodes image attachments and passes them via Ollama's `images: [...]` field on the last user message. Router auto-picks a vision model when a non-vision model is requested with an image attachment. Emits `vision_attached` SSE event.

- [ ] **Audio → text.** Pull `whisper.cpp` binary; new endpoint `/api/audio/transcribe`; composer accepts audio drop. Optional — deferred.

### Tier 3 — agentic depth

- [x] **Auto-verify code.** `POST /api/sandbox/run` runs Python via macOS sandbox-exec. Frontend renders a `▶ Run` button next to Copy on every Python code block in assistant messages; output panel shows stdout/stderr + exit code. On non-zero exit, a `🔧 Ask model to fix` button pre-fills the composer with the code + traceback so the user can hit Send.

- [x] **Session scratchpad tool.** New `backend/session_notes.py` + `save_note`/`read_notes` tools. Notes stored per-conversation with optional labels (plan/todo/constraint/etc.); auto-injected into the system prompt on every new turn.

- [x] **URL-fetch tool.** New `fetch_url` agent tool wrapping `extractors.fetch_url_as_text`. Model can now read a specific page (paste a link, follow a search result) instead of only searching.

- [x] **Cross-workspace retrieval.** New setting `cross_workspace_retrieval` — when on, `rag.retrieve` drops the project scope and searches every workspace. Both vector and BM25 paths respect it.

- [x] **Auto-corpus refresh.** `scripts/refresh_corpus.py` — `git pull` each corpus repo, re-ingest project files under changed dirs with `force=True`. Prints per-repo status. Cron snippet in the docstring.

### Tier 4 — feedback + observability

- [x] **👍 / 👎 on responses.** `backend/feedback.py` + `message_feedback` table (FK cascade to messages). `POST /api/feedback` + `GET /api/feedback?message_id=…`. Frontend adds 👍/👎 buttons to every assistant message; clicking the active thumb again unrates. Foundation for retrieval weighting / LoRA candidate selection later.

- [x] **RAG debug drawer.** Orchestrator emits new `retrieval_debug` SSE event carrying all hits with fused/rerank/vector/BM25 scores. Frontend renders a collapsible `🔍 Retrieval details` panel with a per-chunk table.

- [x] **Hallucination guard.** New `backend/grounding.py`. After the response is complete, splits it into sentences (≥20 chars each), embeds them + retrieved chunks, and computes max cosine per sentence. Sentences below `threshold=0.55` flagged as unsupported. Emits `grounding_check` SSE event with coverage %, per-sentence support, list of unsupported sentences. Frontend renders a color-coded `NN% grounded` badge. Opt-in via `grounding_check` setting (default on when RAG returned chunks).

- [x] **Model A/B mode.** `POST /api/chat/compare` runs both models in parallel via `asyncio.gather`, returns each model's answer + tokens/tps. Assistant messages get an `⚖️ Compare` button that opens a modal with side-by-side rendered markdown from both models. Verified: `"what is CSRF?"` against `llama3.2:1b` vs `dolphin3` returned two distinct, on-topic answers.

### Tier 5 — polish / housekeeping

- [x] **Delete the two duplicate "Audit Workspace Alpha" test projects.** Both removed; only `Default Workspace`, `🛡️ Security Expert`, `💻 Coding Expert` remain.
- [x] **File-hash cache-busting.** `server.py` computes a sha256 over `app.js` / `markdown.js` / `api.js` / `state.js` / `app.css` on every `GET /` and substitutes `__ASSET_HASH__` in the HTML template. Any code change → new hash → auto-invalidated browser cache.
- [x] **Prompt template library.** 10 curated templates across Security / Coding / Research / Meta. New 📝 Templates button in the composer opens a modal; click a template → prefills composer.
- [x] **Command palette (⌘K).** Existing search modal extended: `>` prefix (or `?`) enters command mode with fuzzy match over `new`, `settings`, `templates`, `toggle sidebar`, plus dynamic `model <name>` and `workspace <name>` entries.
- [x] **Slash commands.** `/model <name>` / `/workspace <name>` / `/new` / `/clear` / `/templates` / `/settings` / `/help` — intercepted client-side in `sendMessage`, no LLM roundtrip.

---

## Non-goals (still)

- Full weight fine-tuning. RAG + reranker + specialist models get us most of the way.
- Cloud inference or telemetry. On-device only.
- New frontend framework. Vanilla-ESM stays.

## Execution log

- **2026-09-12** — Plan drafted. Baseline surveyed: 6 models (~53 GB), 5,758 RAG chunks, 2 expert workspaces, ~3.6k backend LOC.
- **2026-09-12** — **Tier 1 shipped** in one pass. All in `backend/rag.py` + `backend/agent_orchestrator.py` + settings toggles (`use_hyde`, `use_reranker`, `use_mmr`, `auto_route_model` — all default on):
  - **HyDE** (`_hyde_expand`, `_HYDE_SYSTEM`): fast model (llama3.2:1b) writes a 2-3 sentence hypothetical answer; that's what gets embedded. Proved value in A/B — the raw query *"How do I properly handle errors in Rust with the ? operator"* returned **0 hits** with plain hybrid retrieval but **4 excellent hits** with HyDE (the model wrote a plausible Rust-error passage that matched the Book's `ch09-*` chapters exactly).
  - **LLM reranker** (`_llm_rerank`, `_RERANK_SYSTEM`): after RRF fusion, top-20 candidates are scored 0-10 by `dolphin3` via JSON output. Reordering demonstrably surfaces on-topic chunks that scored low on both vector and BM25 individually.
  - **MMR diversity** (`_mmr`): iteratively picks the candidate maximizing `λ·relevance − (1−λ)·max_sim_to_picked`. λ=0.5. In the SQL-injection A/B, this replaced a duplicate `A03_2021-Injection.md` chunk with `GraphQL_Cheat_Sheet.md` for broader coverage.
  - **Model router** (`route_model` in orchestrator): regex-based classifier picks `deepseek-r1:14b` for reasoning keywords, `qwen2.5-coder:32b` for code, `llama3.2:1b` for trivial. Per-workspace defaults still win. Emits `event: model_selected` SSE so the UI can show what got routed and why. All 6 test cases picked correctly.
  - **Iterative Think-Deeply**: critique+revise now loops up to `MAX_THINK_ITERATIONS=3`, breaks early on `NO ISSUES` from the reviewer. Emits `iteration` + `max_iterations` in the `thinking_phase` and `critique` events so the UI can show progress.
- **2026-09-12** — Server restarted with cache-bust `?v=7`; end-to-end smoke test on `/api/rag/query?q=how+do+I+protect+against+CSRF+with+cookies` returns `Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.md` as top hit (rerank score 8/10, MMR-diversified). `deepseek-r1:14b` (9 GB) has finished downloading and is available to the router.

- **2026-09-12** — **Tier 2 shipped** (PDF + URL + Vision):
  - `backend/extractors.py`: pypdf for PDFs (skips image-only gracefully), extended text file allowlist (~35 extensions).
  - `/api/files/upload` now uses the shared extractor — same code path works for `.pdf`, `.md`, `.py`, `.rst`, etc.
  - `POST /api/files/from-url` new endpoint. httpx fetch with browser UA + follow-redirects + 15s timeout. Trafilatura extracts main content, strips chrome. Saved as `.md` with `# Title\n\nSource: URL\n\n` header so citations are useful. Verified on RFC 8446 (314 KB → 114 chunks after chunker fix).
  - Chunker bug fixed: single long paragraphs (as returned by many web extractors) now hard-split with overlap. RFC 8446 went from **2 chunks (315 KB in one!)** to **114 chunks** (~3200 chars each). `ingest_file` now reads full file from disk on re-ingest, not just the truncated 4000-char DB preview.
  - Vision: pulled `minicpm-v` (~4.4 GB). Orchestrator now base64-encodes image attachments and attaches them to the last user message via Ollama's `images` field. `route_model` auto-picks a vision model when an image is attached and the requested model can't see. New SSE event `vision_attached` for UI awareness.
  - Server cache-bust bumped to `?v=8`.

- **2026-09-12** — **Tier 3 shipped** (all 5 items). Server cache-bust `?v=9`.
  - `backend/session_notes.py`: per-conversation scratchpad. Table `session_notes(id, conversation_id, note_key, text, created_at)` with FK cascade. `save_note`/`read_notes`/`clear_notes` + `format_for_prompt` injector.
  - `backend/agent_tools.py`: added `fetch_url`, `save_note`, `read_notes` tools + registered them in `AVAILABLE_TOOLS`. Model now sees 6 tools total. `dispatch_tool` auto-injects `conversation_id` into scratchpad tools so the model doesn't need to know it.
  - `agent_orchestrator.py`: injects `session_notes.format_for_prompt(...)` into effective_system on every turn.
  - `backend/rag.py`: `cross_workspace_retrieval` setting (default off) — drops project scope from both vector and FTS queries when on.
  - `POST /api/sandbox/run` — thin wrapper over `security.run_sandboxed_python`. Verified: `print(2+2)` → `stdout: "4"`, `sandboxed: true`.
  - `static/js/markdown.js`: Python code blocks get a `▶ Run` button. Output renders in a `.code-run-output` panel with color-coded stdout/stderr. On error, a `🔧 Ask model to fix` button pre-fills the composer with the code + traceback in a full "fix this" prompt. CSS additions in `app.css` for `.code-run-*` classes.
  - `scripts/refresh_corpus.py`: idempotent corpus refresh — git-pulls each `corpus/{security,coding}/*` repo, re-ingests project files that live under updated dirs with `force=True`. Docstring includes a ready-to-paste cron snippet.

- **2026-09-12** — **Tier 4 shipped** (all 4 items). Server cache-bust `?v=10`.
  - `backend/feedback.py`: `message_feedback` table, `record`/`get_for_message`/`summary`. `POST /api/feedback` (record) + `GET /api/feedback` (single or summary). Frontend: 👍/👎 buttons on assistant messages with active-toggle to unrate.
  - `retrieval_debug` SSE event carries fused/rerank/vector/BM25 scores per chunk. UI renders a `🔍 Retrieval details` collapsible with a per-chunk table.
  - `backend/grounding.py`: sentence-level RAG-support check via cosine to retrieved chunks. `grounding_check` SSE event + color-coded `NN% grounded` badge in the UI. Opt-in via `grounding_check` setting (default on).
  - `POST /api/chat/compare` runs 2 models in parallel via `asyncio.gather`. Frontend adds ⚖️ Compare button on assistant messages that opens a modal with two model dropdowns + side-by-side rendered answers.

- **2026-09-12** — **Tier 5 shipped** (all 5 polish items).
  - Deleted both "Audit Workspace Alpha" duplicates.
  - `server.py` now computes `_asset_hash()` from the 5 primary frontend files on every `GET /` and substitutes it for `__ASSET_HASH__` in `index.html`. First render at `?v=b045059087df`; after this tier's changes → `?v=c0533a616af0`. Manual `?v=N` bumps are gone forever.
  - `PROMPT_TEMPLATES` list in `app.js` (10 items across Security / Coding / Research / Meta) + 📝 Templates composer button + modal renderer.
  - Search modal's `handleGlobalSearch` extended: `>` → command mode. `_paletteCommands()` enumerates static commands (new/settings/templates/toggle sidebar) + dynamic `model <name>` per installed model + `workspace <name>` per project.
  - `sendMessage` intercepts `/`-prefixed input and dispatches through `handleSlashCommand(...)` — supports `/model`, `/workspace` (alias `/ws`), `/new`, `/clear`, `/templates`, `/settings`, `/help`. Escape with `//`.
