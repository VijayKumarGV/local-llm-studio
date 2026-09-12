# Changelog

All notable changes to Local LLM Studio are recorded here. This file
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
uses [SemVer](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-12

First stable release. Contents mirror the twelve-week transformation
from a working proof-of-concept into a professional-grade tool. See
[`docs/RELEASE_NOTES_v1.0.md`](docs/RELEASE_NOTES_v1.0.md) for the
narrative.

`v1.0.0-rc.1` (also tagged 2026-09-12) contained the same set — no
changes between the RC and the final tag; the RC was pinned for the
one-day dogfood sanity pass.

### Ship-readiness (Week 11)
- **Tests** — coverage pushed to 65% with focused unit suites for
  `agent_tools`, RAG chunking, and 14 edge-case defenses against auth
  spoofing / chunker unicode / cost + audit / onboarding shape.
- **E2E** — pytest-playwright smoke suite that boots uvicorn in a
  background thread with ollama pointed at a black-hole port, exercised
  in `.github/workflows/e2e.yml`.
- **Load** — `loadtest/health.js` (k6) baselines the three hot paths
  (`/health` p95 < 50 ms, `/rag/query` p95 < 500 ms, `/sandbox/run`
  p95 < 3 s).
- **Legal** — LICENSE (Apache 2.0), NOTICE, PRIVACY, CODE_OF_CONDUCT,
  CONTRIBUTING.

### UX (Weeks 9–10)
- **First-run wizard** — 5-step modal driven by `GET /api/onboarding/status`
  + streaming `POST /api/models/pull`. Dismiss decision persisted.
- **Recovery banners** — actionable red/amber banners for ollama down /
  embed model missing / upload retry, wired to real endpoints. Upload
  path retries 3× with exponential backoff.
- **Shortcuts** — `⌘K` / `⌘N` / `⌘B` / `⌘⇧M` / `⌘/` / `⌘↵` / `⌘⇧R`
  with a `?` overlay listing them. Single source-of-truth registry in
  `static/js/keybindings.js`.
- **A11y** — skip-to-content link, `aria-live` region announced on
  stream start/stop, `aria-label` on every icon button, `aria-hidden`
  on decorative SVGs, `:focus-visible` outline.
- **Mobile** — three breakpoints (desktop / icon rail / drawer). Scrim
  on `< 900 px`. 16 px composer to avoid iOS Safari zoom-on-focus.
- **Voice** — `/api/audio/{status,transcribe,tts}` with graceful 503
  fallback when whisper / piper aren't installed. Mic button pulses
  red; `🔊` button auto-decorates every assistant message.
- **Docs** — 9-page MkDocs Material site deployed to GitHub Pages by
  `.github/workflows/docs.yml`.

### Quality & observability (Weeks 7–8)
- **Prompt versioning** — six load-bearing system prompts extracted
  from string literals into `prompts/*.md`, loaded by a tiny cached
  loader.
- **Eval harness** — deterministic JSONL spec runner with retrieval-hit
  and answer must-contain / must-not-contain grading. `--compare-baseline`
  gates on any pass→fail regression or > 2 pp aggregate drop.
- **Feedback digest** — weekly markdown rollup of 👎 responses grouped
  by workspace/model + non-stopword theme extraction.
- **Metrics** — Prometheus `/metrics` with seven custom counters +
  histograms; RAG retrieve wrapped for latency + hit distribution;
  chat stream wrapped for active-streams gauge + terminal-status
  labelling.
- **Tracing** — opt-in OpenTelemetry via `OTEL_EXPORTER_OTLP_ENDPOINT`.
  Manual span in `rag.retrieve`.
- **Observability stack** — separate `docker/observability-compose.yml`
  runs Prometheus + Grafana + Tempo alongside the studio. Five
  provisioned dashboards (Overview, RAG, Models, Feedback, Alerts) +
  four alert rules.
- **Cost ledger** — per-turn prompt + completion token accounting
  exposed via `GET /api/cost/summary`.

### Packaging (Weeks 5–6)
- **Docker** — multistage `python:3.12-slim` Dockerfile + compose
  stack (Ollama + studio) with localhost-only ports and named
  volumes. `scripts/first_run.sh` idempotent bootstrap.
- **CI publish** — multi-arch GHCR publish on `v*.*.*` tag + non-tag
  smoke build.
- **macOS `.app`** — PyInstaller bundle + `rumps` menu-bar tray +
  `pynput` ⌥⌘Space hotkey + best-effort GitHub Releases update
  checker. `desktop/README.md` covers sign + notarize.

### Security (Weeks 3–4)
- **Auth** — session bearer token + `/auth` cookie bootstrap.
  Constant-time compare. Path-traversal fix on file uploads.
- **Hardening** — CSP + `X-Frame-Options: DENY` + Referrer-Policy +
  Permissions-Policy on every response. Middleware ordered so 401s
  keep their security headers.
- **Rate limiting** — slowapi per-endpoint limits.
- **Prompt-injection scanner** — heuristic warn-or-block with 6
  regex patterns.
- **Layered sandbox** — Docker → sandbox-exec → unsandboxed opt-in.
  Preflight sandbox-exec so hardened macOS hosts degrade to
  `unavailable` instead of failing every user program.
- **Sensitive settings → Keychain** — allowlist-first routing via
  the `keyring` module.
- **Append-only audit log** — `GET /api/audit`. Never raises upward.
- **Supply chain** — `pip-audit` in CI + `requirements-lock.txt` +
  Dependabot for pip / github-actions / docker.

### Foundation (Weeks 1–2)
- **Ollama routing fix** — vision-capable models retained when
  attachments include images.
- **Isolated test infra** — `temp_db` + `fresh_schema` fixtures;
  schema re-initialization after DB monkeypatch.
- **CI** — `macos-14` runner running ruff + mypy + pytest with
  coverage.
- **Types** — mypy strict-ish with a `backend/types.py` TypedDict
  module.
- **Observability foundation** — request-ID `contextvar` propagated
  through every log line.
- **Backup** — nightly SQLite snapshot script + monthly restore drill.

---

Prior to `v1.0.0` the project was tracked as `v0.2.0` through
`v0.11.0`; the intermediate tags remain in git but each week's contents
are recorded above.
