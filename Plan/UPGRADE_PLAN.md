# Upgrade Plan — Local LLM Studio (M4 Pro Edition)

Progress key: `[ ]` pending · `[~]` in progress · `[x]` completed

Last updated: 2026-09-11

---

## High impact

- [x] **[Backend] Multi-step agent loop is single-shot.** `agent_orchestrator.py:155-303` declares `MAX_AGENT_STEPS = 8` but never loops — tools run once and their results are never fed back to the model. → Wrap the Ollama call in a `for step in range(MAX_AGENT_STEPS)` loop; after each tool executes, append `{"role":"tool","content":result}` and re-call. This is the biggest functional gap.

- [x] **[Backend] Native Ollama tool calling not used.** Uses regex `<tool_call>` parsing (`agent_orchestrator.py:34-67`) — brittle. Qwen 2.5 and Ollama 0.3+ support the `tools=[...]` field on `/api/chat` with structured JSON responses. → Migrate to native tool calling; delete the regex path.

- [x] **[Backend] Event loop blocked by sync HTTP.** `urllib.request.urlopen` runs inside `async` handlers. → Migrated to shared `httpx.AsyncClient` (`backend/ollama_client.py`); streaming iterator is now truly async.

- [x] **[Backend] "Sandbox" isn't one.** → `security.py:run_sandboxed_python` now wraps the subprocess in `sandbox-exec` with a deny-by-default profile that blocks network and disallows writes outside the scratch dir. `agent_tools.execute_python_code` delegates to it. Permission matrix wired into `agent_orchestrator.run_agent_loop`.

- [x] **[Frontend] Hand-rolled markdown + XSS surface.** → Replaced with `marked` + `highlight.js` + `DOMPurify` (loaded from esm.sh). Final DOM sanitized. Delegated copy-button handler.

- [x] **[Infra] No RAG / embeddings.** → `backend/rag.py` chunks uploaded files, embeds them with `nomic-embed-text` via Ollama, stores float32 embeddings as BLOBs in SQLite, retrieves top-k by cosine each turn. Wired into `/api/files/upload` and the orchestrator.

## Medium impact

- [x] **[Backend] Web search scrapes DuckDuckGo HTML.** → Now uses the `ddgs` package (falls back to `duckduckgo_search` if only that's installed).

- [x] **[Backend] Stale default model.** → All `hermes3` defaults across `server.py`, `database.py`, `backup.py`, `agent_orchestrator.py`, and the frontend replaced with `qwen2.5:32b`.

- [x] **[Backend] SQLite has no FTS.** → Added `messages_fts` FTS5 virtual table + triggers, snippet highlighting, and a backfill on first upgrade. `global_search` uses MATCH with a fallback to LIKE if FTS5 isn't compiled in.

- [x] **[Backend] No dependency manifest.** → Added `requirements.txt` and `pyproject.toml`; `start_web_ui.sh` now installs from `requirements.txt` and re-installs when the file changes.

- [x] **[Backend] Binds `0.0.0.0` in `__main__`.** → Binds `127.0.0.1`; CORS restricted to `http://127.0.0.1:8080` and `http://localhost:8080`.

- [x] **[Frontend] No message edit/regenerate/branch UI hook.** → `branchFromMessage`, `editMessage`, `regenerateLast` were already implemented but shown in the message action bar. Model picker now shows vision/thinking/tools/coding badges + context window (e.g. `qwen2.5:32b 🔧💻 · 32K`). Image previews already work in both the attachment strip and message rows.

- [x] **[Docs] `MODEL_REFERENCE_AND_UPGRADES.md` is stale.** → Rewritten for M4 Pro, `qwen2.5:32b` baseline, macOS commands, native tool calling section, RAG walkthrough.

## Low impact

- [x] **Token estimator was `len/3.8`.** → Uses `tiktoken` cl100k_base with a char-based fallback. `keep_alive` is now sent on every Ollama call (default `30m`, override via `settings.keep_alive`).

- [x] **No migrations.** → Added `backend/migrations.py` (yoyo wrapper), `migrations/00001_baseline.sql`, invoked from the lifespan hook.

- [x] **Tests exist but no runner declared.** → `pytest` added to deps. `test_suite.py::test_all` and `test_audit.py::test_audit` both run under `pytest -v`. `test_audit` gets a `skipif` when the server isn't up. Fixed the compaction assertion that had been calibrated to hermes3's old 8K window.

- [x] **Inline `onclick=` handlers in `index.html`.** → All top-level HTML inline handlers replaced with `data-action="…"` and a single delegated click listener. Template-string handlers inside app.js template literals were left in place (not an XSS risk since they never touch model output).

- [x] **No `--reload` on dev; no health endpoint; no structured logging.** → Added `/api/health` (reports Ollama + model count + embed model). `start_web_ui.sh` picks up `DEV=1` / `RELOAD=1` env vars to enable `--reload`. `logging.basicConfig` set at import time; server code uses a named `studio` logger.

---

## New files

- `backend/ollama_client.py` — shared `httpx.AsyncClient` for Ollama, opened on lifespan startup, closed on shutdown.
- `backend/rag.py` — chunking + embedding + top-k retrieval pipeline.
- `backend/migrations.py` — yoyo wrapper.
- `migrations/00001_baseline.sql` — placeholder for future migrations.
- `requirements.txt` + `pyproject.toml` — dependency manifest.

## Execution log

- **2026-09-11** — completed all 18 items in one sitting. Old venv had a corrupt Python 3.9 + 3.14 mix; rebuilt from scratch with 3.14. Tests green. Sandbox verified: `print(1+1)` works, `urllib.request.urlopen('https://example.com')` denied.
