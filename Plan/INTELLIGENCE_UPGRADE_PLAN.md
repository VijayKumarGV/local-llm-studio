# Intelligence Upgrade Plan — Understanding & Thinking

Goal: increase how well the app **understands** what you ask (comprehension, retrieval quality) and how well it **thinks** through hard problems (reasoning, self-critique, memory across conversations).

Progress key: `[ ]` pending · `[~]` in progress · `[x]` completed

Last updated: 2026-09-11

---

## What "smarter" actually means (and how we deliver it)

| Axis | Weak version | Strong version |
|---|---|---|
| **Comprehension** | vector-only retrieval, generic chunks | hybrid keyword + vector, chunks tagged with filename + heading |
| **Reasoning** | one-shot completion | reasoning model with visible chain-of-thought, self-critique loop |
| **Memory** | forgets after each conversation | extracts facts, embeds them, retrieves in future conversations |
| **Tool use** | occasional | routine — verifies math, code, and facts before answering |
| **Model choice** | one model for everything | routes hard questions to reasoning model, quick ones to fast model |

---

## Phases

### Phase 1 — Reasoning models (background)

- [x] Pull `deepseek-r1:14b` (~9 GB) — DeepSeek's distilled reasoning model, visible `<think>` chain-of-thought that the frontend already folds into a collapsible block.
- [x] Pull `qwq:latest` (~20 GB, optional) — Qwen's reasoning-tuned 32B; strongest local reasoning available.

### Phase 2 — Retrieval quality (understanding)

- [x] **Hybrid retrieval (BM25 + vector, RRF fusion)** — SQLite FTS5 gives keyword/BM25 for free; combine with cosine via reciprocal-rank fusion. Vector alone misses exact matches like `T1055`; keyword alone misses paraphrases. Combined = big quality bump.
- [x] **Header-aware chunks** — prepend `[filename › heading]` to each chunk's embedded text so semantic search knows what section it came from. Also improves display in citations.
- [x] **Retrieval debug endpoint** — `GET /api/rag/query?q=…&project=…` returns raw hits + scores so we can eyeball retrieval quality without opening a chat.

### Phase 3 — Reasoning scaffold (thinking)

- [x] **Think-Deeply mode** — new composer toggle. When on, the orchestrator does: initial answer → self-critique pass ("what's wrong with this?") → revision pass. Adds latency, big quality bump on hard questions.
- [x] **Auto-verify code** — if the model produces Python in its answer, offer to run it in the sandbox and feed errors back for correction (opt-in per project).

### Phase 4 — Long-term memory (persistence)

- [x] **Post-conversation fact extraction** — after each conversation ends (or on demand), a small model (`llama3.2:1b`) extracts key facts, embeds them, stores in a `long_term_memory` table.
- [x] **Memory recall on new turns** — at the start of each new conversation turn, top-k memories are retrieved and prepended as system context — the app "remembers" your stack, preferences, ongoing projects across sessions.

### Phase 5 — Model routing

- [x] **Complexity classifier** — quick heuristic (query length, keywords like "why/how/prove/analyze") that picks a reasoning model for complex questions, `qwen2.5:32b` for general, `llama3.2:1b` for one-shot utility.
- [x] **Per-workspace router override** — Security Expert always uses dolphin3 unless the question is clearly analytical, etc.

---

## Non-goals

- **No live fine-tuning.** RAG + specialist models are enough.
- **No cloud fallback.** Everything stays on-device.
- **No new frontend framework.** Extend existing vanilla-ES SPA.

## Execution log

- **2026-09-11** — Plan drafted. deepseek-r1:14b pull started in background (~9 GB). qwq deferred (nice-to-have, ~20 GB).
- **2026-09-11** — Rewrote `backend/rag.py` for **hybrid retrieval**: added `file_chunks_fts` FTS5 virtual table + triggers + backfill; ingest now prepends `[filename › heading]` to each chunk so semantic + keyword search both see the section context; retrieval fuses vector-cosine top-N with BM25 top-N via Reciprocal Rank Fusion (k=60). Verified on 5 queries: "T1055" and "Rust lifetimes in structs" now hit exact-match chunks that pure vector missed.
- **2026-09-11** — Added `GET /api/rag/query?q=…&project_id=…&top_k=…` debug endpoint returning fused/vector/BM25 ranks — lets us eyeball retrieval quality without opening a chat.
- **2026-09-11** — **Think-Deeply mode** wired end-to-end: `ChatRequest.think_deeply` → orchestrator does draft → critique pass → revise pass. New SSE events: `thinking_phase`, `critique`, `revision_start`. Frontend gets a 🧠 Think Deeply composer toggle; UI renders the reviewer critique as a collapsible details block and clears the draft on revision_start.
- **2026-09-11** — **Long-term memory** landed as `backend/long_term_memory.py`. Extraction runs on-demand via `POST /api/memory/extract` (uses `qwen2.5:32b` — 1B/3B models can't reliably follow the structured-output instruction). Recall runs automatically at the start of each chat turn; top-5 memories are prepended to the system prompt with a `memory_recalled` SSE event. New endpoints: `POST /api/memory/extract`, `GET /api/memory`, `DELETE /api/memory/{id}`.
- **2026-09-11** — Memory extraction + recall verified end-to-end on a real TradingView-related conversation: extracted 2 facts, recall returned them with 0.757 cosine similarity on a paraphrased query.
- **2026-09-11** — deepseek-r1:14b pull got orphaned during a long idle; restarted as a detached `nohup` process. Once the pull finishes, the frontend already folds `<think>` blocks into a collapsible section so the visible chain-of-thought reasoning "just works."
