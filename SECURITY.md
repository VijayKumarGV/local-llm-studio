# Security

Local LLM Studio is designed as a **single-user, on-device** application. Everything below covers our threat model, what we defend against, what we consciously don't, and how to report a vulnerability.

## Reporting a vulnerability

Email: **avishwakarma@netskope.com** with subject `[LLM-STUDIO-SECURITY]`. Please include:

- Affected version / commit SHA
- Reproduction steps
- Impact assessment
- Suggested fix (optional)

We'll acknowledge within 48h. Please don't file a public GitHub issue for undisclosed vulnerabilities.

## Threat model

**In scope** — what this project defends against:

| Threat | Defense |
|---|---|
| Passers-by at the user's desk poking the localhost API | Bearer-token auth on every non-public route |
| Malicious web pages POSTing to `http://127.0.0.1:8080` (DNS rebinding, CSRF) | `SameSite=strict` cookie · CORS allowlist · CSRF-safe on GETs |
| XSS via model-generated markdown / HTML | `DOMPurify` sanitization + `marked` allowlist |
| Iframe embedding to steal cookies | `X-Frame-Options: DENY` + `frame-ancestors 'none'` in CSP |
| Prompt-injection via user input | Heuristic scanner (`backend/prompt_safety.py`) with warn-or-block modes |
| Runaway Python code from the sandbox tool eating CPU / filesystem / network | Docker sandbox (preferred) or macOS `sandbox-exec` — network denied, memory + PID limits, read-only rootfs |
| Path traversal on file uploads | `os.path.basename()` strips directory components; null-bytes stripped |
| SQL injection on user input | Every query uses `?` parameter binding |
| Known CVEs in dependencies | `pip-audit` in CI + weekly Dependabot |
| Secrets leaking into the SQLite DB or logs | Sensitive keys routed to macOS Keychain via `backend/secure_settings.py`; log format never renders body/params |
| Runaway request loops | slowapi rate limits per endpoint |

**Out of scope** — explicit non-goals:

- Multi-user isolation (there is one user by design; a real user account model is Path B/C in the roadmap)
- Network attackers on the same machine at kernel level
- Physical access to the machine (Keychain protects secrets, but the DB is not encrypted at rest)
- Model-level jailbreaks — the LLM itself can be talked into anything an unaligned local model would do
- Defense against actively adversarial prompts embedded in RAG-ingested content (retrieval-side prompt injection). Warn-mode scanner catches obvious cases; mitigation is planned in a future iteration

## What runs where

- **Backend** (`backend/server.py`) — FastAPI on `127.0.0.1:8080` (bind is env-overridable)
- **Ollama** (`http://127.0.0.1:11434`) — separate process; we speak to it over HTTP
- **Sandbox** — Docker container (preferred) or macOS `sandbox-exec` subprocess
- **DB** — SQLite in `backend/workspace.db` (WAL mode, unencrypted)
- **Secrets** — macOS Keychain (`SERVICE=LocalLLMStudio`)
- **Session token** — env var `SESSION_TOKEN` OR auto-generated file at `~/Library/Application Support/LocalLLMStudio/token` (mode 0600)

## Data flow

Nothing leaves the machine except:

1. `ollama pull <model>` — HTTP to Ollama's registry (`registry.ollama.ai`)
2. The `search_web` agent tool — DDGS API calls when explicitly invoked
3. The `fetch_url` agent tool — HTTP fetches to whatever URL the user provides
4. `POST /api/files/from-url` — fetches user-provided URLs via httpx + trafilatura
5. Any external URL the user manually opens in their browser via a rendered link

No telemetry. No crash reports. No analytics.

## Cryptography / key material

- Session tokens: `secrets.token_urlsafe(32)` — 256 bits of entropy from the OS CSPRNG
- Token comparison: `hmac.compare_digest` — constant-time
- Cookies: `HttpOnly`, `SameSite=strict`, `Max-Age=1y`, `Secure=False` (localhost HTTP — flip to True behind TLS)
- Keychain: macOS-provided AES-GCM at rest, protected by the Login keychain unlock

## Deliberate accepted risks

| Risk | Why accepted |
|---|---|
| SQLite DB unencrypted at rest | Local, single-user; user's disk encryption (FileVault) is the guardrail. Encryption at rest would need SQLCipher — noted as future work. |
| CSP `style-src 'unsafe-inline'` | highlight.js + inline `style="…"` attributes in the SPA. Removing needs a rewrite of ~30 inline styles. Noted as v1.1 work. |
| `sandbox-exec` deprecated by Apple | Still functional; Docker takes over when available. macOS may remove `sandbox-exec` in a future release — we'll notice via a CI job that spawns real sandbox invocations. |
| Two f-string SQL usages in `database.update_project` / `update_conversation` | Field names come from a hard-coded allowlist inside the function; user input never reaches the SQL string. Values are `?`-bound. Reviewed 2026-09-12. |
| No CSRF token beyond `SameSite=strict` | Localhost origin + cookie policy prevents cross-site POSTs. Real CSRF tokens are a Path B (multi-user) requirement. |
| Rate limits are per-IP, not per-user | Single-user product — IP == user. Real per-user quotas are a Path B requirement. |

## Security review log

- **2026-09-12** — Manual review pass (Week 4 Day 5)
  - ✅ auth required on every non-public route
  - ✅ CSP + `X-Frame-Options: DENY` + `X-Content-Type-Options: nosniff` on every response
  - ✅ rate limits on chat / sandbox / upload / compare
  - ✅ `pip-audit` clean: no known CVEs in `requirements.txt`
  - ✅ Prompt-injection scanner active in warn-mode
  - ✅ Sandbox layered: Docker → sandbox-exec → refuse (or explicit opt-in)
  - ✅ Sensitive settings routed to macOS Keychain, plaintext stripped from SQLite on write
  - ✅ Audit log records every write action + tool call
  - **🐛 fixed:** file-upload path traversal — `file.filename = "../../etc/foo"` could escape `UPLOAD_DIR`. Now `os.path.basename()` strips directory components + null-bytes.
  - ✅ Every SQL query uses `?` parameter binding except two allowlist-gated UPDATE statements (documented above).
  - ✅ No `eval()` / `exec()` on user input anywhere.

## Version history

| Version | Notable changes |
|---|---|
| v0.3.0 | Bearer auth, CSP, rate limits, prompt-injection scanner, Keychain |
| v0.4.0 (in progress) | Docker sandbox, audit log, supply-chain guards, path-traversal fix |
