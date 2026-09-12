# Roadmap & Maturation — where this project can go

Honest assessment as of 2026-09-12. Four possible directions, a shared "make it professional" checklist, and a recommended 90-day plan.

---

## 1. Where you actually are today

**Strengths (unusually good for a hobby-scale app):**
- Multi-step agent loop with native Ollama tool calling
- Hybrid retrieval (FTS5 BM25 + vector cosine, RRF-fused) + HyDE + LLM rerank + MMR
- Sandboxed Python execution (macOS `sandbox-exec`, deny-network by default)
- Two curated expert workspaces backed by 5,700+ embedded chunks from authoritative sources (OWASP, MITRE, CWE, Rust Book, Python docs, TS Handbook, Go docs)
- Long-term memory + session scratchpad + grounding/hallucination check
- Iterative Think-Deeply (critique → revise loop up to N iterations)
- Model router that picks specialist models by question shape / attachments
- 👍/👎 feedback plumbing, A/B compare, retrieval-debug drawer
- Backend: async httpx, FastAPI lifespan hooks, yoyo migrations, structured logging, health endpoint
- Frontend: modern SPA with proper markdown+DOMPurify, command palette, slash commands, prompt templates, custom tooltips, Lovable-inspired visual polish

**Limitations that block "real-world" use:**
| Category | Gap |
|---|---|
| **Multi-user** | Single-tenant. No auth, no user isolation, no per-user workspaces. |
| **Deployment** | Runs from `./start_web_ui.sh` on one Mac. No Docker, no installer, no package. |
| **Reliability** | 2 tests total. No CI. No error tracking. |
| **Security** | CORS wide-ish, no rate limiting, no CSP headers, secrets are env vars, DB unencrypted at rest. |
| **Scale** | SQLite (fine for 1 user), in-Python cosine (fine ≤~50k chunks), single Ollama backend (no failover). |
| **Observability** | Structured logs exist. No metrics, no traces, no dashboards beyond `/api/health`. |
| **Portability** | macOS-only sandbox. Python 3.14 (new — many libs not yet on it). Ollama-locked. |
| **Data lifecycle** | No backup schedule, no restore drill, no data-model versioning strategy beyond yoyo. |
| **Legal / packaging** | No LICENSE file, no third-party attribution manifest, no privacy policy, no changelog. |

---

## 2. Four directions the project could go

### A — "Personal power tool" (my recommendation for now)

**Target:** you (and maybe a few technical friends) use it daily as your primary LLM interface.

**Effort:** 2–3 weeks of weekend work.

**What to build:**
- Packaged macOS `.app` (PyInstaller or py2app) that bundles the server + a small tray-app launcher
- Menu-bar icon; launches Ollama and the server on click; global hotkey (⌥⌘Space) to summon
- iCloud Drive sync of `workspace.db` + `corpus/` (or a `sync` command using `rsync`/git)
- Better model manager UI (browse Ollama library, pull with visible progress)
- Voice input via `whisper.cpp` + voice output via `piper`
- Screenshot → composer via macOS Shortcuts integration
- Native "Ask about this PDF" quick action in Finder / Preview

**Why this first:** minimum surface area, maximum daily-life value, keeps everything on-device. Everything you learn here informs the harder paths later.

### B — "Small-team collaborative"

**Target:** 5–50 users in one org (security team, engineering team, research lab).

**Effort:** 4–8 weeks focused work.

**What to build:**
- Auth: WebAuthn or OIDC (Keycloak/Authentik self-hosted)
- Multi-tenancy schema: users → workspaces (personal + shared) → conversations
- Postgres backend (keep SQLite path for single-user)
- Docker Compose stack: app + Postgres + Ollama + Nginx
- Kubernetes Helm chart for org deployment
- Real RBAC: tool permissions per role, workspace visibility rules
- Audit log of all tool executions + prompts
- Team feedback rollup: which retrievals actually helped
- Shared corpus with per-user overlays

### C — "Vertical SaaS / on-prem product"

**Target:** paying customers in regulated domains (law, healthcare, defense, finance) who cannot use cloud LLMs.

**Effort:** 3–6 months minimum with a serious go-to-market.

**What to build (product):**
- Every-thing from B, plus:
- Multi-tenancy (org / user / workspace / role)
- SSO (SAML, OIDC), audit exports, DLP hooks
- Per-domain corpus packs (OWASP+MITRE for SecOps, HIPAA+FDA for healthtech, GAAP+SEC for finance)
- White-label / customer branding
- Managed model updates + optional LoRA per customer
- Compliance packs: SOC 2 Type II, HIPAA BAA, ISO 27001

**Non-technical needs:** sales, security review responses, customer success, pricing/packaging, legal (terms, DPA, MSA), a real company.

### D — "Best-in-class open source"

**Target:** compete with Open WebUI / LM Studio / Jan.ai / LibreChat as the default local-LLM workspace.

**Effort:** 6–12 months, community-driven.

**What to build:**
- Apache-2.0 license + contribution guide + CoC + governance model
- Plugin system (like VS Code extensions) for tools, workspaces, models
- Marketplace for expert corpora (versioned, signed)
- Multi-backend: Ollama + llama.cpp + MLX + vLLM + LM Studio + OpenAI-compatible endpoints
- Cross-platform: Mac (already), Linux, Windows (Docker + native)
- Documentation site, guides, examples
- Discord/Matrix community

---

## 3. The "make it professional" checklist (shared across every path)

Anything past personal use needs these. Ranked by blocking-ness.

### 3.1 Reliability & correctness

- [ ] **Test coverage ≥60%.** Currently 2 tests. Backend needs pytest coverage on `rag`, `agent_orchestrator`, `security`, `long_term_memory`, `feedback`, `grounding`. Frontend needs Playwright e2e for at least: open workspace, send message, upload file, run code block, thumbs feedback.
- [ ] **CI on every push.** GitHub Actions: `ruff` + `mypy` + `pytest` + `npm run typecheck` (if we add TS eventually) + build the Docker image.
- [ ] **Type checking.** `mypy --strict` on backend/. Currently no static typing enforcement.
- [ ] **Error tracking.** Sentry (or self-hosted GlitchTip) capturing exceptions with request IDs.
- [ ] **Request IDs.** Every request gets a UUID, threaded through logs + errors + SSE events.
- [ ] **Graceful shutdown.** Drain in-flight SSE streams before uvicorn exits.
- [ ] **Retries + timeouts.** Every outbound Ollama/embed call has explicit timeout + retry with exponential backoff (currently timeout only).

### 3.2 Security

- [ ] **Auth even for single-user.** Simple bearer token from a `SESSION_TOKEN` env var; browser stores in localStorage. Prevents anyone at the machine from using it.
- [ ] **CSP header.** Strict Content-Security-Policy blocking inline scripts and eval.
- [ ] **Rate limiting.** Per-IP per-endpoint via `slowapi` or nginx.
- [ ] **Prompt-injection scanner** on user input (heuristic + LLM classifier for high-value tenants).
- [ ] **Sandbox review.** `sandbox-exec` is deprecated (though still works). Migration path: Docker container or Apple's App Sandbox with entitlements.
- [ ] **Secrets in Keychain.** Right now settings are in the SQLite DB unencrypted. Move sensitive settings (API keys for third-party APIs) to macOS Keychain.
- [ ] **Signed model checksums.** Verify `ollama pull` outputs against expected digest before trusting a new model.
- [ ] **Audit log** of every tool execution + who triggered it (needed the moment auth exists).

### 3.3 Data engineering

- [ ] **Backups scheduled + tested.** Cron: nightly `sqlite3 backup` + retain 30d + monthly restore drill.
- [ ] **Migrations gated in CI.** Fail the build if a migration modifies data-loss-y things without an opt-in flag.
- [ ] **Postgres option.** For team scale — same schema, different driver. Keep SQLite as default.
- [ ] **Vector store swap.** Numpy-cosine is fine to ~50k chunks. Above that: LanceDB (single-file, Rust-fast) or Qdrant (server-based, HNSW). Have the swap-in interface ready.
- [ ] **Corpus versioning.** `corpus/security/owasp_cheatsheets @ commit sha` recorded in DB; re-ingest triggers on drift.
- [ ] **Data-model versioning.** Explicit schema_version + doc in `Plan/`.

### 3.4 Observability

- [ ] **Metrics.** Prometheus `/metrics` endpoint. Counters: requests_total, tool_calls_total, retrieval_hits, feedback_total. Histograms: request_latency, retrieval_latency, model_tps.
- [ ] **Traces.** OpenTelemetry spans on each request: retrieve → embed → llm → grounding. Export to Jaeger or Tempo.
- [ ] **Dashboards.** Grafana boards: throughput, error rate, cache-hit rate, feedback trend, per-model tps.
- [ ] **Cost tracking.** Per-user, per-workspace, per-model daily token spend (matters for cloud fallback later).
- [ ] **Alerting.** Retrieval hit rate drops, feedback negativity spike, ollama down, disk full.

### 3.5 DevOps & packaging

- [ ] **Docker image + docker-compose.** Ships app + Ollama + volumes + healthchecks.
- [ ] **Kubernetes Helm chart** for team deploys (path B+).
- [ ] **Semantic versioning + changelog.** `CHANGELOG.md` auto-updated from conventional commits.
- [ ] **Update mechanism.** For desktop path: Sparkle framework or a self-check + banner.
- [ ] **All paths configurable via env vars.** No hardcoded `/Users/…` in code.

### 3.6 Product / UX

- [ ] **First-run wizard.** Detect no models → walk user through pulling qwen2.5:32b + nomic-embed-text; detect no workspaces → offer to build the two expert ones.
- [ ] **Docs site.** MkDocs or Docusaurus. User guide + API reference + architecture doc.
- [ ] **Accessibility pass.** aria labels, keyboard-only navigation, WCAG AA color contrast, screen-reader friendly SSE announcements.
- [ ] **Mobile-responsive layout.** Two-column collapse below 900px; usable on iPad.
- [ ] **i18n framework.** Even if only English day one, structure for translation.

### 3.7 Model / retrieval quality (the "expert" claim needs backing)

- [ ] **Eval harness.** 100+ curated Q/A pairs per expert workspace with expected reference chunks + answer keys. Nightly run computes: retrieval hit@k, answer support %, ROUGE/BLEU vs reference. Track over time.
- [ ] **Regression gate.** New model / prompt change must not drop headline metric >2%.
- [ ] **Human eval workflow.** 👍/👎 data → weekly digest of worst-scored responses for manual review → prompt or corpus fix.
- [ ] **Prompt versioning.** System prompts in files, not code, tracked in git, A/B-able.
- [ ] **LoRA pipeline productionized.** Not just a script — reproducible, dockerized, checkpointed, deployable as an Ollama Modelfile.

### 3.8 Legal / operational

- [ ] **LICENSE file** (Apache 2.0 recommended for OSS, dual-license for SaaS).
- [ ] **Third-party attribution.** `NOTICE.md` listing OWASP (CC-BY-SA), MITRE (public), python.org (PSF), etc.
- [ ] **Privacy policy** — even for local. States "no data leaves your machine except: (a) `ollama pull`, (b) explicit web-search tool calls, (c) URLs you click."
- [ ] **Contribution guide + CoC** (if OSS).
- [ ] **Trademark check** on name if going product-y. "Local LLM Studio" is generic — probably fine but confirm.

---

## 4. Recommended 90-day plan (Path A, foundation for anything else)

Assumes ~10 hours/week solo. Sequential-ish, but many items parallelize.

### Weeks 1–2 — Reliability foundation
1. `pytest` coverage to ~50%: rag, orchestrator, feedback, grounding, extractors
2. GitHub Actions CI (ruff + mypy + pytest + build)
3. Fix any type errors mypy surfaces
4. Add request IDs + Sentry-like error capture
5. Backup script + restore drill

### Weeks 3–4 — Security hardening
6. Auth: bearer-token from `SESSION_TOKEN` env, browser stores in cookie
7. CSP + rate limiting
8. Prompt-injection detector on user input
9. Migrate `sandbox-exec` → Docker sandbox (or App Sandbox)
10. Move sensitive settings to Keychain

### Weeks 5–6 — Deploy & distribute
11. Docker image + docker-compose
12. macOS `.app` bundle via PyInstaller
13. Menu-bar tray app + global hotkey
14. Update mechanism (banner + auto-download)

### Weeks 7–8 — Quality signals
15. Eval harness with 100 Q/A per workspace
16. Prometheus `/metrics` + Grafana dashboard
17. Feedback-driven weekly digest of worst responses
18. Prompt files → git-tracked

### Weeks 9–10 — Polish for users
19. First-run wizard (models + workspaces)
20. Docs site (MkDocs)
21. Accessibility pass
22. Mobile-responsive layout
23. Voice input (whisper.cpp)

### Weeks 11–12 — Choose the next fork
24. Ship v1.0 (personal power tool complete)
25. Decide: continue Path A polish, or start Path B (multi-user) / Path D (OSS launch)

---

## 5. Key risks & decisions

**Risks to watch:**
- **Python 3.14 lock-in.** Many libs not tested; downgrade to 3.12 for wider compat before shipping v1.
- **Ollama-only backend.** If Ollama's business model changes, we're stuck. Wrap it early behind a `ModelProvider` interface.
- **macOS-only sandbox.** Blocks Linux/Windows adoption; Docker sandbox is the portable answer.
- **License mix in corpus.** OWASP is CC-BY-SA (share-alike), Rust Book is Apache/MIT, MITRE is US-gov public. Repackaging OWASP requires the SA clause; check before distributing the corpus with the app.

**Decisions to make in the next 2 weeks:**
1. **License.** Apache 2.0 / MIT / AGPL / dual-license?
2. **Naming.** "Local LLM Studio" is fine as a project name but weak as a product name. If Path C is on the table, consider rebranding early.
3. **Backend stance.** Commit to Ollama only, or plan the abstraction now?
4. **Distribution model.** Free OSS · freemium · pure commercial · consulting-driven?

---

## 6. Honest self-assessment

The bones are professional-grade for a hobby project. The gap to "real-world team tool" is mostly *non-model* work — auth, deployment, tests, observability, docs. The gap to "commercial product" is much bigger (sales, compliance, support, marketing) and largely non-engineering.

If you keep building for yourself, this is already the best local-LLM UI I've seen most of. If you want it to matter to others, the next 90 days are about making it *reliable, deployable, and documented* — not adding more clever RAG tricks.
