# Expert Mode Plan — Cybersecurity + Coding Specialization

Goal: turn Local LLM Studio into a highly-capable **cybersecurity expert** and **software engineering expert** using authentic, publicly-licensed reference material — without any full fine-tuning.

Progress key: `[ ]` pending · `[~]` in progress · `[x]` completed

Last updated: 2026-09-11

---

## Strategy (why RAG > fine-tuning here)

An LLM can be "upgraded" to expert-level in a domain in four ways: (1) pick a model already fine-tuned for the domain, (2) inject an expert persona via system prompt, (3) put authoritative references at its fingertips via RAG so answers cite primary sources, or (4) fine-tune the weights. Options 1–3 give ~90% of the benefit for ~5% of the cost, and they compose — that's the approach here.

## Phases

### Phase 1 — Specialist models

- [x] Pull `qwen2.5-coder:32b` — elite code generation, refactoring, debugging (~20 GB). *Necessary for coding expertise.*
- [x] Pull `dolphin3.0-llama3.1` — uncensored 8B model that can explain OWASP/CWE material without refusing (~5 GB). *Necessary because base models often refuse to explain even textbook security concepts.*
- [x] Skip: `whiterabbitneo` (not on Ollama library, would need HF conversion) and `deepseek-r1:14b` (nice-to-have, not needed for MVP).

### Phase 2 — Curated corpus

Download **only** official, authoritative, appropriately-licensed sources. No scraping proprietary content.

**Security sources:**
- [x] OWASP Cheat Sheet Series — MIT (`github.com/OWASP/CheatSheetSeries`)
- [x] OWASP Top 10 2021 — CC-BY-SA (`github.com/OWASP/Top10`)
- [x] OWASP ASVS — CC-BY-SA (`github.com/OWASP/ASVS`)
- [x] MITRE ATT&CK Enterprise — public (`github.com/mitre/cti`)
- [x] CWE Top 25 — public (`cwe.mitre.org`)
- [x] PayloadsAllTheThings — MIT (`github.com/swisskyrepo/PayloadsAllTheThings`) — only READMEs (index summaries per attack)

**Coding sources:**
- [x] Rust Book — Apache 2.0 / MIT (`github.com/rust-lang/book`)
- [x] Python tutorial — PSF license (`github.com/python/cpython/Doc/tutorial`)
- [x] Effective Go — CC-BY-3.0 (`go.dev/doc/effective_go`)
- [x] TypeScript handbook — MIT (`github.com/microsoft/TypeScript-Website`)
- [x] Real Python design patterns overview — public
- [x] MDN Web Docs subset — CC-BY-SA (skipped for MVP — too large)

### Phase 3 — Ingestion

- [x] `scripts/curate_corpus.py` downloads all above with `git clone --depth 1` and stores under `corpus/{security,coding}/`.
- [x] `scripts/build_expert_workspaces.py` creates two projects via the local API, uploads matching files, triggers RAG ingestion (embed via `nomic-embed-text`).

### Phase 4 — Expert workspaces

- [x] **🛡️ Security Expert** project — system prompt anchors to OWASP/MITRE/NIST; default model `dolphin3.0-llama3.1`; retrieves from security corpus.
- [x] **💻 Coding Expert** project — senior-engineer system prompt; default model `qwen2.5-coder:32b`; retrieves from coding corpus.

### Phase 5 — Verification

- [x] Query "Explain SQL injection with a code example and OWASP reference" in Security Expert → confirm RAG citations appear.
- [x] Query "Write an idiomatic Rust error type hierarchy" in Coding Expert → confirm quality vs. base model.

---

## Non-goals

- **No full fine-tuning.** LoRA on M4 is possible but 12+ hour job; RAG already delivers 90% of the benefit.
- **No scraping copyrighted content** (paywalled security books, O'Reilly, etc.).
- **No offensive-ops enablement.** Framing is educational, defensive, CTF, and authorized-testing — same framing that OWASP + SANS + MITRE use.

## Execution log

- **2026-09-11** — plan drafted; sandbox blocked corpus git clones; user approved option A (fetch official OWASP/MITRE/language repos).
- **2026-09-11** — `scripts/curate_corpus.py` created and executed. All 9 sources cloned; 960 files after pruning non-doc content. Pull of `qwen2.5-coder:32b` (~19 GB) and `dolphin3` (~5 GB) restarted with proper `nohup` so they survive shell exit.
- **2026-09-11** — `backend/rag.py` upgraded to Ollama's batch `/api/embed` endpoint (32 chunks per HTTP round-trip, falls back to per-item `/api/embeddings` if unavailable). Verified: 3 test texts → 3 vectors × 768 dim.
- **2026-09-11** — `scripts/build_expert_workspaces.py` created and started; ingesting 960 files into two projects with `nomic-embed-text`.
- **2026-09-11** — First ingest wedged on the 54 MB MITRE ATT&CK STIX bundle (would produce ~16k chunks in one file). Killed. Exploded the bundle inline into **1,757 per-technique / per-tactic / per-mitigation markdowns**, deleted the raw JSON, added `MAX_CHUNKS_PER_FILE=200` guard and skip-if-already-embedded logic to `backend/rag.py`.
- **2026-09-11** — Second ingest completed cleanly. Final counts: **🛡️ Security Expert → 2,169 files / 3,861 chunks**, **💻 Coding Expert → 516 files / 1,897 chunks**. Total 5,758 embedded chunks.
- **2026-09-11** — Fixed `rag.retrieve` `ambiguous column name: project_id` bug (unqualified column in JOIN). Semantic retrieval verified on four representative queries — SQL injection prevention, MITRE T1055 process injection, Rust structs, Python asyncio. All returned high-scoring, on-target chunks.
- **2026-09-11** — `dolphin3:latest` (4.9 GB) pull complete; set as default model for the Security Expert workspace. `qwen2.5-coder:32b` still downloading (43%, ETA ~15 min); Coding Expert will fall back to `qwen2.5:32b` (also excellent at code) until the coder variant lands.
- **2026-09-11** — `qwen2.5-coder:32b` (19 GB) pull complete. Upgraded Coding Expert default model. Both expert workspaces now running on their fully-preferred model.
