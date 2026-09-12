# 90-Day Professional-Grade Playbook (Path A)

Detailed, execute-in-order playbook to take Local LLM Studio from hobby-grade to reliable-personal-tool that could deploy to a small team. Every week has: goal, deliverables, concrete tasks, files touched, definition of done.

Last updated: 2026-09-12

---

## How to use this doc

1. Work top-to-bottom. Weeks depend on each other (CI depends on tests, Docker depends on env-config, etc.).
2. Each week has a **Definition of Done** — don't move on until it's green.
3. Every task lists **files touched** so you can eyeball scope.
4. Ship one thing per commit. Use conventional-commits (`feat:`, `fix:`, `chore:`, `test:`, `docs:`).
5. Anything marked `[optional]` can slip without blocking the next week.

## Repo hygiene (do once, day 0)

**Before any of the below**, spend 30 min on plumbing:

- [ ] `git init` if not already, `.gitignore` for `.venv/`, `backend/workspace.db*`, `backend/uploads/`, `corpus/`, `.playwright-mcp/`, `verify_*.png`, `ui_*.png`, `studio-loaded.png`, `.pytest_cache/`, `__pycache__/`, `*.egg-info/`.
- [ ] Push to GitHub as private repo.
- [ ] Set up branch protection: no direct push to `main`, PRs required, CI must pass.
- [ ] Enable Dependabot for pip + GitHub Actions.
- [ ] Add `pre-commit` framework — hooks for ruff, mypy, and pytest-fast (staged files only).

## Ground rules

**Branch strategy:** `main` is always deployable. Work on `feat/<name>` branches, PR into main, squash-merge.

**Versioning:** semver. Today = pre-alpha `0.1.0`. Target v1.0 at end of week 12. Bump minor on any user-visible change; patch on fixes; major only on breaking changes.

**Commit style:** conventional-commits.
```
feat(rag): add HyDE query expansion
fix(sandbox): handle whitespace in code paths
test(feedback): add roundtrip integration test
```

**Testing philosophy:**
- **Unit** tests for pure logic (chunker, cosine, model router heuristics, feedback DB).
- **Integration** tests for endpoints (real SQLite, real Ollama for RAG paths — skip when Ollama down).
- **e2e** (Playwright) for critical user flows only. Slow but catch real regressions.
- Aim for ~60% line coverage on backend; don't chase 100%.

**Time estimates** assume ~10 h/week solo. Adjust to your reality.

---

# PHASE 1 — RELIABILITY FOUNDATION (Weeks 1–2)

Goal: nothing else matters if the code can silently break. Every change from now on ships with tests + CI.

## Week 1 — Testing baseline

**Goal:** raise pytest coverage from ~5% → 40% on backend/. Establish test patterns for the rest of the plan.

**Deliverables:**
- [ ] `pytest --cov=backend` reports ≥40%
- [ ] Every new backend module has at least one test
- [ ] `tests/` directory (separate from `backend/`) with proper structure
- [ ] `conftest.py` with fixtures for temp DB + fake ollama client

### Day 1 — Test infrastructure

**Files created/touched:**
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/backend/__init__.py`
- `pyproject.toml` (add pytest config)
- `.gitignore` (add `.coverage`, `htmlcov/`)

**`tests/conftest.py`:**
```python
"""Shared fixtures. Each test gets an isolated SQLite DB + mocked ollama."""
import os, tempfile, sqlite3, pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture
def temp_db(monkeypatch):
    """Isolated SQLite DB path per test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("backend.database.DB_PATH", path)
    yield path
    os.unlink(path)

@pytest.fixture
def fresh_schema(temp_db):
    from backend import database, rag, long_term_memory, session_notes, feedback
    database.init_db()
    rag.ensure_schema()
    long_term_memory.ensure_schema()
    session_notes.ensure_schema()
    feedback.ensure_schema()
    yield temp_db

@pytest.fixture
def fake_ollama():
    """Patched ollama client that returns canned responses."""
    with patch("backend.ollama_client.get_ollama_client") as m:
        client = AsyncMock()
        m.return_value = client
        yield client
```

**`pyproject.toml` additions:**
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra --cov=backend --cov-report=term-missing --cov-report=html --cov-fail-under=40"
asyncio_mode = "auto"

[tool.coverage.run]
omit = ["backend/test_*.py", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = ["pragma: no cover", "raise NotImplementedError", "if __name__"]
```

Move existing `backend/test_suite.py` and `backend/test_audit.py` → `tests/backend/legacy/` so they still run but out of the way.

Install: `pytest-cov pytest-asyncio pytest-httpx`.

**Definition of done:** `.venv/bin/pytest` runs, coverage reports show baseline number.

### Day 2 — Pure-logic tests (highest ROI first)

**Target modules with pure functions — no I/O needed:**

`tests/backend/test_context_manager.py`:
- `estimate_tokens("")` → 0
- `estimate_tokens("hello world")` → some positive number, both tiktoken and fallback
- `prepare_compacted_context` with 100 messages, tiny model → summary block present, budget respected
- Attachment context truncation

`tests/backend/test_model_capabilities.py`:
- Registry lookup by exact name
- Prefix match fallback
- Vision validation for text-only model with image attachment
- Vision validation for vision model with image attachment (should not warn)

`tests/backend/test_rag_chunking.py`:
- `_chunk_with_headings("")` → `[]`
- Short text (1 paragraph) → 1 chunk
- Text with markdown headings → headings preserved in chunk metadata
- Very long single paragraph (no blank lines) → hard-split with overlap (the RFC bug)
- Text with paragraphs → chunks ≤ target size, overlap ≥0
- `_annotate` prepends `[filename › heading]`

`tests/backend/test_agent_orchestrator_routing.py`:
- `route_model(...)` for reasoning keywords → deepseek-r1 if installed
- `route_model(...)` for code keywords → qwen2.5-coder
- `route_model(...)` trivial query → llama3.2:1b
- `route_model(...)` with image → vision model
- `_has_image_attachment` variations

**Definition of done:** ~15–20 tests, all pass, coverage on those 4 modules > 70%.

### Day 3 — Feedback / notes / memory DB roundtrips

Use the `fresh_schema` fixture.

`tests/backend/test_feedback.py`:
- Record +1 → get_for_message returns +1
- Record -1 over +1 → replaced (only latest kept)
- Record 0 → row deleted
- Summary counts

`tests/backend/test_session_notes.py`:
- FK constraint fires on missing conversation_id
- save_note → read_notes returns it
- Filter by note_key
- clear_notes drops all

`tests/backend/test_long_term_memory.py`:
- `_parse_facts` handles: array, single object, `{facts: [...]}`, prose-wrapped JSON, garbage
- `extract_from_conversation` with mocked ollama returning JSON
- `recall` returns top-k by cosine

**Definition of done:** DB integration tests pass with real SQLite.

### Day 4 — Endpoint integration tests

`tests/backend/test_server_endpoints.py`:
```python
import pytest
from fastapi.testclient import TestClient
from backend.server import app

@pytest.fixture
def client(fresh_schema):
    return TestClient(app)

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")

def test_create_project_and_list(client):
    r = client.post("/api/projects", json={"name": "Test"})
    assert r.status_code == 200
    pid = r.json()["project"]["id"]
    r = client.get("/api/projects")
    assert any(p["id"] == pid for p in r.json()["projects"])

def test_conversation_lifecycle(client):
    proj = client.post("/api/projects", json={"name": "P"}).json()["project"]
    conv = client.post("/api/conversations", json={"project_id": proj["id"]}).json()["conversation"]
    client.patch(f"/api/conversations/{conv['id']}", json={"title": "Renamed"})
    got = client.get(f"/api/conversations/{conv['id']}").json()
    assert got["conversation"]["title"] == "Renamed"

def test_feedback_roundtrip(client):
    # ... setup, then thumbs up/down
    ...
```

Aim for ~15 endpoint tests. **Do not** test streaming chat here — that goes in Playwright.

**Definition of done:** all CRUD endpoints have at least one happy-path test.

### Day 5 — Sandbox + extractor tests

`tests/backend/test_security.py`:
- `sanitize_and_resolve_path("README.md")` → valid absolute path
- `sanitize_and_resolve_path("../../etc/passwd")` → raises `SecurityException`
- `run_sandboxed_python("print(2+2)")` → status success, stdout "4"
- `run_sandboxed_python("import time; time.sleep(30)", timeout_seconds=1)` → status timeout
- `run_sandboxed_python("import urllib.request; urllib.request.urlopen('https://example.com')")` → network denied (sandboxed=True + stderr)

`tests/backend/test_extractors.py`:
- Read a fixture `.txt` file → correct text
- Read a fixture `.md` file → correct text
- Read a fixture 3-page PDF → text from all pages
- Read a fixture image-only PDF → empty string, no exception

Add fixture files under `tests/fixtures/`.

**Definition of done:** `pytest --cov` reports ≥40%. Commit + push. Week 1 complete.

---

## Week 2 — CI, mypy, backup script

**Goal:** every push runs tests + typecheck. Backups happen nightly.

### Day 1 — GitHub Actions CI

**File: `.github/workflows/ci.yml`:**
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: macos-14  # ARM runner, matches your dev env
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }  # 3.14 is bleeding-edge; switch back to 3.12 for CI stability
      - name: Install
        run: |
          python -m venv .venv
          .venv/bin/pip install -r requirements.txt -e ".[dev]"
      - name: Ruff
        run: .venv/bin/ruff check backend/ tests/
      - name: Mypy
        run: .venv/bin/mypy backend/
      - name: Pytest
        run: .venv/bin/pytest --cov-fail-under=40
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with: { files: ./coverage.xml }
```

Add `ruff` and `mypy` to `[project.optional-dependencies].dev` in pyproject.toml.

**Ruff config** (in `pyproject.toml`):
```toml
[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "A", "C4", "PIE", "SIM", "RET"]
ignore = ["E501"]  # line-length handled by formatter

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]  # asserts fine in tests
```

Run `ruff check --fix backend/ tests/` locally, commit fixes.

### Day 2 — Python 3.12 downgrade

**Why:** 3.14 is 3 months old. Many libs (uvloop, some ML libs) don't have 3.14 wheels. CI on 3.12 = wider compat.

- [ ] Update `pyproject.toml` `requires-python = ">=3.12,<3.14"`
- [ ] Recreate venv with 3.12: `/opt/homebrew/bin/python3.12 -m venv .venv`
- [ ] Reinstall requirements
- [ ] Run tests, fix any 3.14-only syntax you accidentally used
- [ ] Update `start_web_ui.sh` to prefer python3.12

### Day 3 — Mypy strict mode

**File: `pyproject.toml`:**
```toml
[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true
files = ["backend"]

[[tool.mypy.overrides]]
module = ["backend.test_*", "backend.legacy.*"]
ignore_errors = true
```

Run `mypy backend/`. Expect ~30–100 errors initially. Fix in this order:
1. Add return-type annotations to all functions (`-> None`, `-> dict[str, Any]`, etc.)
2. Fix `Any` misuse where a specific type is obvious
3. Add `| None` where variables are optional
4. Add `TypedDict` for the shape of tool results, retrieval hits, etc.

Create `backend/types.py`:
```python
"""Shared type aliases and TypedDicts."""
from typing import TypedDict, Any, Literal

class RetrievalHit(TypedDict):
    id: str
    file_id: str
    chunk_index: int
    text: str
    filename: str
    score: float
    vector_score: float
    bm25_rank: int | None
    vector_rank: int | None

class ToolResult(TypedDict, total=False):
    status: Literal["success", "error", "timeout", "denied", "skipped", "blocked"]
    error: str
    stdout: str
    stderr: str
    return_code: int
    sandboxed: bool
```

Replace `Dict[str, Any]` with these TypedDicts where possible.

**Definition of done:** `mypy backend/` returns 0 errors.

### Day 4 — Request IDs + structured logging

**File: `backend/middleware.py` (new):**
```python
"""Per-request context: request_id, latency, structured log line."""
import time, uuid, logging
from contextvars import ContextVar
from fastapi import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
log = logging.getLogger("studio.request")

async def request_context_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
    request_id_var.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        dur_ms = (time.perf_counter() - start) * 1000
        log.info(
            "%s %s %s %.1fms",
            rid, request.method, request.url.path, dur_ms,
        )

class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True
```

Wire in `server.py`:
```python
app.middleware("http")(request_context_middleware)
# Update logging.basicConfig format:
logging.basicConfig(
    format="%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
    ...
)
logging.getLogger().addFilter(RequestIdFilter())
```

Every SSE event should also carry `request_id`.

### Day 5 — Backup script

**File: `scripts/backup_db.sh` (new):**
```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Library/Application Support/LocalLLMStudio/backups}"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/workspace_$STAMP.db"

# SQLite online backup — safe even while server is running.
sqlite3 "$ROOT/backend/workspace.db" ".backup '$DEST'"
gzip -9 "$DEST"
echo "backup → $DEST.gz"

# Prune >30d
find "$BACKUP_DIR" -name "workspace_*.db.gz" -mtime +30 -delete

# Weekly restore drill: on the 1st of each month, restore into a temp file
# and verify the schema matches.
if [ "$(date +%d)" = "01" ]; then
  TMP=$(mktemp)
  gunzip -c "$DEST.gz" > "$TMP"
  ROWS=$(sqlite3 "$TMP" "SELECT COUNT(*) FROM projects;")
  echo "restore drill: $ROWS projects readable from $DEST.gz"
  rm "$TMP"
fi
```

Install cron:
```bash
crontab -l 2>/dev/null | { cat; echo "0 3 * * * '$ROOT/scripts/backup_db.sh' >> $HOME/Library/Application\ Support/LocalLLMStudio/backup.log 2>&1"; } | crontab -
```

**Definition of done:** CI passes on push, `mypy` clean, request IDs visible in logs, first backup written.

**Week 2 wrap:** commit + tag `v0.2.0`. First public checkpoint.

---

# PHASE 2 — SECURITY HARDENING (Weeks 3–4)

Goal: even single-user local app needs auth (someone sitting at your desk) and hardening (a malicious page shouldn't be able to POST to localhost).

## Week 3 — Auth + CSP + input validation

### Day 1 — Bearer token auth

**Design:** simple bearer token stored in an env var. On first launch, if `SESSION_TOKEN` is unset, generate a random one, print it, and write to `~/Library/Application Support/LocalLLMStudio/token`. Browser reads via a one-time bootstrap URL `/auth?token=<t>` which sets a `Set-Cookie`.

**File: `backend/auth.py` (new):**
```python
"""Bearer-token auth. Single user, but non-trivially blocks passersby."""
import os, secrets, hmac
from pathlib import Path
from fastapi import Request, HTTPException, status

TOKEN_FILE = Path.home() / "Library/Application Support/LocalLLMStudio/token"
_TOKEN: str | None = None

def load_or_create_token() -> str:
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    env = os.environ.get("SESSION_TOKEN")
    if env:
        _TOKEN = env
        return _TOKEN
    if TOKEN_FILE.exists():
        _TOKEN = TOKEN_FILE.read_text().strip()
        return _TOKEN
    _TOKEN = secrets.token_urlsafe(32)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(_TOKEN)
    TOKEN_FILE.chmod(0o600)
    print(f"[auth] first-run token generated at {TOKEN_FILE}")
    print(f"[auth] visit http://127.0.0.1:8080/auth?token={_TOKEN} to bootstrap the browser cookie")
    return _TOKEN

def _constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

async def require_auth(request: Request):
    if request.url.path.startswith(("/api/health", "/auth", "/static", "/favicon")):
        return
    if request.url.path == "/":
        return  # index.html itself is fine; JS will 401 on API calls if not authed
    token = load_or_create_token()
    presented = request.cookies.get("studio_token") or ""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        presented = auth[7:]
    if not _constant_eq(presented, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
```

**Wire in `server.py`:**
```python
from backend.auth import require_auth, load_or_create_token
from fastapi.responses import RedirectResponse

app.middleware("http")(request_context_middleware)

@app.middleware("http")
async def auth_middleware(request, call_next):
    try:
        await require_auth(request)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    return await call_next(request)

@app.get("/auth")
def bootstrap_auth(token: str):
    if not hmac.compare_digest(token, load_or_create_token()):
        raise HTTPException(401)
    resp = RedirectResponse("/")
    resp.set_cookie("studio_token", token, httponly=True, samesite="strict", max_age=60*60*24*365)
    return resp
```

**Frontend:** if any API call returns 401, render a small overlay "Paste your session token" — user copies from `~/Library/Application Support/LocalLLMStudio/token` and clicks "Save". Frontend POSTs to `/auth?token=…`.

**Test:** `tests/backend/test_auth.py` — unauthed request → 401, authed → 200.

### Day 2 — CSP + security headers

**File: `backend/security_headers.py` (new):**
```python
"""Add HTTP security headers to every response."""
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://esm.sh; "
    "style-src 'self' 'unsafe-inline' https://esm.sh; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

async def security_headers_middleware(request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    return resp
```

Note: `'unsafe-inline'` on style-src stays because of hljs theme; move away once we self-host highlight.js.

**Verify:** Open browser devtools → Network → look at response headers.

### Day 3 — Rate limiting

Install `slowapi`. Add to `pyproject.toml` deps.

**File: `backend/rate_limit.py` (new):**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
```

Wire in server.py:
```python
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from backend.rate_limit import limiter

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Apply stricter limits on hot endpoints:
```python
@app.post("/api/chat/stream")
@limiter.limit("20/minute")
async def stream_chat(request: Request, req: ChatRequest): ...

@app.post("/api/sandbox/run")
@limiter.limit("30/minute")
async def sandbox_run(...): ...

@app.post("/api/files/upload")
@limiter.limit("60/hour")
async def upload_file(...): ...
```

### Day 4 — Input validation + prompt injection scanner

**Pydantic:** every endpoint uses `BaseModel` inputs with `Field(..., max_length=N)`. Audit the current `Request` body reads and convert to schemas.

**Prompt-injection heuristic scanner:**

**File: `backend/prompt_safety.py` (new):**
```python
"""Cheap prompt-injection heuristics. Not perfect — just catches the obvious.
Real defense is the model itself + not blindly trusting tool outputs."""
import re

_PATTERNS = [
    (re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I), "instruction_override"),
    (re.compile(r"you\s+are\s+now\s+DAN|jailbreak|roleplay\s+as", re.I), "persona_override"),
    (re.compile(r"reveal\s+(your\s+)?system\s+prompt", re.I), "prompt_exfiltration"),
    (re.compile(r"<\|(im_end|im_start|system|user|assistant)\|>", re.I), "chat_template_injection"),
    (re.compile(r"repeat\s+the\s+word[s]?\s+.{1,20}\s+forever", re.I), "resource_exhaustion"),
]

def scan(text: str) -> list[dict[str, str]]:
    findings = []
    for pattern, kind in _PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append({"kind": kind, "match": m.group(0)[:80]})
    return findings
```

Wire in orchestrator (log-only, do not block by default):
```python
from backend.prompt_safety import scan
findings = scan(user_message)
if findings:
    log.warning("prompt injection heuristic hit: %s", findings)
    yield f"event: prompt_warning\ndata: {json.dumps({'findings': findings})}\n\n"
```

Setting `block_prompt_injection` (default off) can be enabled to actually reject.

### Day 5 — Sensitive settings → Keychain

Install `keyring`. Add to deps.

**File: `backend/secure_settings.py` (new):**
```python
"""Sensitive settings (API keys for third-party services) live in macOS Keychain
instead of the SQLite settings table. Non-sensitive settings stay in DB."""
import keyring
SERVICE = "LocalLLMStudio"

_SENSITIVE = {"tavily_api_key", "brave_api_key", "openai_api_key"}

def get_secret(key: str) -> str | None:
    if key not in _SENSITIVE:
        return None
    return keyring.get_password(SERVICE, key)

def set_secret(key: str, value: str) -> None:
    if key not in _SENSITIVE:
        raise ValueError(f"{key} is not a sensitive setting")
    keyring.set_password(SERVICE, key, value)

def delete_secret(key: str) -> None:
    try:
        keyring.delete_password(SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass
```

Modify `database.get_settings` to overlay Keychain values for sensitive keys.

**Definition of done for Week 3:** all API calls need auth · CSP header on every response · rate-limited · prompt-scan events surface to frontend · secrets in Keychain.

## Week 4 — Sandbox migration + audit log

### Day 1–2 — Docker-based Python sandbox

**Why:** `sandbox-exec` is deprecated by Apple (still works, but they warn). Docker is portable across macOS/Linux and gives us real isolation.

**File: `docker/sandbox.Dockerfile` (new):**
```dockerfile
FROM python:3.12-slim
# No network access at runtime (enforced via --network=none)
# Read-only rootfs, tmpfs for /tmp
RUN adduser --disabled-password --gecos '' sandbox
USER sandbox
WORKDIR /work
CMD ["python"]
```

Build once: `docker build -f docker/sandbox.Dockerfile -t studio-sandbox:latest docker/`.

**Rewrite `backend/security.py::run_sandboxed_python`:**
```python
def run_sandboxed_python(code: str, timeout_seconds: int = 15) -> Dict[str, Any]:
    if shutil.which("docker"):
        return _run_in_docker(code, timeout_seconds)
    if _ON_MACOS and SANDBOX_EXEC:
        return _run_in_sandbox_exec(code, timeout_seconds)   # fallback
    return {"status": "error", "error": "no sandbox available; refusing to run"}

def _run_in_docker(code: str, timeout_seconds: int) -> Dict[str, Any]:
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:size=64m,exec",
        "--memory=256m", "--cpus=1",
        "--pids-limit=64",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "studio-sandbox:latest",
        "python", "-I", "-c", code,
    ]
    # ... same subprocess pattern, timeout, output cap
```

**Test:** verify network is denied, filesystem read-only, memory limited (`import numpy; numpy.zeros(10**9)` should OOM cleanly).

### Day 3 — Audit log

**File: `backend/audit_log.py` (new):**
```python
"""Every write action + every tool execution → append-only audit log."""
import uuid, json
from datetime import datetime
from backend import database

def ensure_schema() -> None:
    with database.get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                actor TEXT DEFAULT 'user',
                action TEXT NOT NULL,
                resource_type TEXT,
                resource_id TEXT,
                request_id TEXT,
                details TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);")
        conn.commit()

def log(action: str, *, resource_type: str = "", resource_id: str = "",
        details: dict | None = None, actor: str = "user") -> None:
    from backend.middleware import request_id_var
    with database.get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), datetime.now().isoformat(), actor, action,
             resource_type, resource_id, request_id_var.get(), json.dumps(details or {})),
        )
        conn.commit()
```

Instrument:
- `orchestrator._run_tool` → `audit_log.log("tool_call", resource_type="tool", resource_id=tool_name, details={"args": …})`
- `server.upload_file` → `log("file_upload", ...)`
- `server.chat_compare` → `log("model_compare", ...)`
- Any DELETE endpoint

Expose `GET /api/audit?limit=100` for viewing.

### Day 4 — Dependency + supply chain

- [ ] `pip-audit` in CI to catch CVE-y dependencies
- [ ] `pip freeze > requirements-lock.txt` — reproducible installs
- [ ] Add `--require-hashes` mode as a future goal (needs hashes)
- [ ] Enable GitHub Dependabot (already done in prereq)

### Day 5 — Security review pass

Manual audit checklist:
- [ ] All endpoints require auth (except `/`, `/auth`, `/api/health`)
- [ ] No `eval()` / `exec()` on user input anywhere
- [ ] SQL uses parameter binding everywhere (search for f-string SQL — should be zero)
- [ ] File paths from user input pass through `security.sanitize_and_resolve_path`
- [ ] `os.path.join` with user input → check for traversal (`..`, absolute paths)
- [ ] Response bodies never leak the SESSION_TOKEN or Keychain secrets
- [ ] CORS origins actually restrictive
- [ ] Model outputs go through DOMPurify (already ✓)

Fix everything red. Document what you decided to accept in `SECURITY.md`.

**Week 4 wrap:** tag `v0.3.0`. Auth + sandbox + audit trail in place.

---

# PHASE 3 — PACKAGING & DISTRIBUTION (Weeks 5–6)

Goal: `git clone && make run` (or double-click a `.app`) — no manual setup.

## Week 5 — Docker + docker-compose

### Day 1 — Config via env

Audit every hardcoded path. Every setting should be overridable by env var. Create `backend/config.py`:
```python
"""Centralized config. Read env vars once, expose as immutable dataclass."""
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Config:
    data_dir: Path
    db_path: Path
    upload_dir: Path
    corpus_dir: Path
    ollama_host: str
    session_token: str | None
    log_level: str
    bind_host: str
    bind_port: int

def load() -> Config:
    data = Path(os.environ.get("STUDIO_DATA_DIR",
                Path.home() / "Library/Application Support/LocalLLMStudio"))
    data.mkdir(parents=True, exist_ok=True)
    return Config(
        data_dir=data,
        db_path=Path(os.environ.get("STUDIO_DB_PATH", data / "workspace.db")),
        upload_dir=Path(os.environ.get("STUDIO_UPLOAD_DIR", data / "uploads")),
        corpus_dir=Path(os.environ.get("STUDIO_CORPUS_DIR",
                        Path(__file__).parent.parent / "corpus")),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        session_token=os.environ.get("SESSION_TOKEN"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        bind_host=os.environ.get("BIND_HOST", "127.0.0.1"),
        bind_port=int(os.environ.get("BIND_PORT", "8080")),
    )

CONFIG = load()
```

Replace `backend/database.py::DB_PATH` etc. with `CONFIG.db_path`. Same for uploads, corpus, ollama host.

### Day 2 — App Dockerfile

**File: `Dockerfile`:**
```dockerfile
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
RUN adduser --disabled-password --gecos '' app
WORKDIR /app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY backend /app/backend
COPY static /app/static
COPY migrations /app/migrations
COPY scripts /app/scripts
ENV STUDIO_DATA_DIR=/data
VOLUME /data
EXPOSE 8080
USER app
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

`.dockerignore`:
```
.venv/
.git/
corpus/
verify_*.png
tests/
.pytest_cache/
htmlcov/
*.log
```

### Day 3 — Compose stack

**File: `docker-compose.yml`:**
```yaml
services:
  ollama:
    image: ollama/ollama:latest
    volumes: ["ollama_models:/root/.ollama"]
    ports: ["11434:11434"]
    # For Apple Silicon acceleration inside Docker Desktop 4.30+
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
    restart: unless-stopped

  studio:
    build: .
    depends_on: [ollama]
    environment:
      OLLAMA_HOST: http://ollama:11434
      STUDIO_DATA_DIR: /data
      LOG_LEVEL: INFO
      SESSION_TOKEN: ${SESSION_TOKEN:-}
    volumes: ["studio_data:/data"]
    ports: ["8080:8080"]
    restart: unless-stopped

volumes:
  ollama_models:
  studio_data:
```

Add a `Makefile`:
```makefile
.PHONY: run dev test lint typecheck build backup

run:      ; docker compose up -d
stop:     ; docker compose down
dev:      ; DEV=1 ./start_web_ui.sh
test:     ; .venv/bin/pytest
lint:     ; .venv/bin/ruff check backend/ tests/
typecheck:; .venv/bin/mypy backend/
build:    ; docker build -t local-llm-studio:latest .
backup:   ; ./scripts/backup_db.sh
```

### Day 4 — Docker Hub / GHCR publish

Extend CI:
```yaml
publish:
  needs: test
  if: startsWith(github.ref, 'refs/tags/v')
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - uses: docker/login-action@v3
      with: {registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }}}
    - uses: docker/build-push-action@v5
      with:
        push: true
        tags: |
          ghcr.io/${{ github.repository }}:${{ github.ref_name }}
          ghcr.io/${{ github.repository }}:latest
        platforms: linux/amd64,linux/arm64
```

### Day 5 — First-run scripts

**File: `scripts/first_run.sh` (new):**
```bash
#!/usr/bin/env bash
set -euo pipefail
echo "== Local LLM Studio first-run =="
echo "1. Pulling required models (may take a while)..."
for m in nomic-embed-text qwen2.5:32b llama3.2:1b; do
  docker exec studio-ollama-1 ollama pull "$m"
done
echo "2. Building curated corpus..."
docker exec studio-studio-1 python scripts/curate_corpus.py
echo "3. Building expert workspaces..."
docker exec studio-studio-1 python scripts/build_expert_workspaces.py
echo "Done. Open http://localhost:8080"
```

**Week 5 wrap:** `docker compose up && open http://localhost:8080` works from a fresh clone. Tag `v0.4.0`.

## Week 6 — Native macOS `.app` + tray

### Day 1 — PyInstaller bundle

Install `pyinstaller`.

**File: `packaging/build_app.py` (new):**
```python
"""Build a standalone macOS .app that bundles server + assets + venv."""
import PyInstaller.__main__
PyInstaller.__main__.run([
    "--name=LocalLLMStudio",
    "--windowed",
    "--onedir",
    "--osx-bundle-identifier=com.avishwakarma.local-llm-studio",
    "--icon=packaging/icon.icns",
    "--add-data=static:static",
    "--add-data=migrations:migrations",
    "--hidden-import=uvicorn.lifespan.on",
    "--hidden-import=uvicorn.protocols.http.h11_impl",
    "packaging/tray_app.py",
])
```

### Day 2 — Menu-bar tray app

Install `rumps` (macOS menu-bar framework in pure Python).

**File: `packaging/tray_app.py` (new):**
```python
"""Tray icon that starts the FastAPI server as a subprocess, offers
show/hide/quit, and opens the browser on click."""
import subprocess, webbrowser, threading, time, signal, atexit, os
import rumps
import httpx

SERVER_URL = "http://127.0.0.1:8080"

class Studio(rumps.App):
    def __init__(self):
        super().__init__("🧠", quit_button=None)
        self.proc = None
        self.menu = ["Open Studio", "Restart Server", "View Logs", None, "Quit"]
        self.start_server()

    def start_server(self):
        env = os.environ.copy()
        env["BIND_HOST"] = "127.0.0.1"
        self.proc = subprocess.Popen(
            ["uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", "8080"],
            env=env,
        )
        threading.Thread(target=self._wait_ready, daemon=True).start()
        atexit.register(self.stop_server)

    def _wait_ready(self):
        for _ in range(30):
            try:
                httpx.get(f"{SERVER_URL}/api/health", timeout=1.0)
                self.title = "🧠"
                return
            except Exception:
                time.sleep(1)
        self.title = "⚠️"

    def stop_server(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=5)

    @rumps.clicked("Open Studio")
    def open_studio(self, _):
        webbrowser.open(SERVER_URL)

    @rumps.clicked("Restart Server")
    def restart(self, _):
        self.stop_server()
        self.start_server()

    @rumps.clicked("View Logs")
    def logs(self, _):
        subprocess.Popen(["open", "-a", "Console", "~/Library/Logs/LocalLLMStudio.log"])

    @rumps.clicked("Quit")
    def quit(self, _):
        self.stop_server()
        rumps.quit_application()

if __name__ == "__main__":
    Studio().run()
```

### Day 3 — Global hotkey

Add `pynput` for global hotkey. Register `⌥⌘Space` → open browser to studio URL.

### Day 4 — Update mechanism

**Strategy:** simple pull-based check. On launch, `GET https://api.github.com/repos/OWNER/REPO/releases/latest`. If newer, show a notification "Update available → click to download."

**File: `packaging/updater.py`:**
```python
import httpx, plistlib
from pathlib import Path
CURRENT = "0.5.0"

def check_latest(repo: str) -> tuple[str, str] | None:
    try:
        r = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=5)
        r.raise_for_status()
        latest = r.json()["tag_name"].lstrip("v")
        if latest > CURRENT:
            return latest, r.json()["html_url"]
    except Exception:
        pass
    return None
```

### Day 5 — Notarization + release automation

- [ ] Apple Developer ID cert setup
- [ ] `codesign --deep --force --sign "Developer ID Application: NAME" LocalLLMStudio.app`
- [ ] `xcrun notarytool submit` for notarization
- [ ] `xcrun stapler staple` to embed the ticket
- [ ] GitHub Actions release job builds + notarizes on tag push
- [ ] Attach `.app.zip` and `.dmg` to the GitHub release

**Week 6 wrap:** double-clickable `.app`, menu-bar icon, autoupdate check, notarized. Tag `v0.5.0`.

---

# PHASE 4 — QUALITY & OBSERVABILITY (Weeks 7–8)

Goal: measure what's actually working, catch regressions before shipping.

## Week 7 — Eval harness + prompt versioning

### Day 1 — Eval spec format

**File: `evals/README.md`:** describes the format.

**File: `evals/security_expert.jsonl` (start with 25 items, grow to 100+):**
```jsonl
{"id": "sec-001", "query": "How do I prevent SQL injection in Python with sqlite3?", "expected_sources": ["SQL_Injection_Prevention_Cheat_Sheet.md"], "answer_must_contain": ["parameterized", "?"], "answer_must_not_contain": ["string concatenation is safe"]}
{"id": "sec-002", "query": "Explain MITRE T1055", "expected_sources": ["T1055_Process_Injection.md"], "answer_must_contain": ["process injection"], "expected_technique_ids": ["T1055"]}
...
```

**File: `evals/coding_expert.jsonl` (25 items):**
```jsonl
{"id": "cod-001", "query": "How do I use the ? operator in Rust for error propagation?", "expected_sources": ["ch09-*.md"], "answer_must_contain": ["Result", "?"]}
...
```

### Day 2 — Eval runner

**File: `evals/run.py` (new):**
```python
"""Run eval spec against a live studio server. Reports:
- Retrieval hit@k (did expected_sources appear in top-K?)
- Answer support % (must_contain matched? must_not_contain avoided?)
- Overall pass rate
- Regression against last run (stored in evals/history/)."""
import json, argparse, asyncio, httpx, time
from pathlib import Path

async def run_spec(client, spec, project_id):
    # RAG check first
    r = await client.get(f"/api/rag/query", params={
        "q": spec["query"], "project_id": project_id, "top_k": 6
    })
    hits = r.json().get("hits", [])
    retrieved_files = {h["filename"] for h in hits}
    expected = set(spec.get("expected_sources", []))
    retrieval_hit = any(any(exp in fn for exp in expected) for fn in retrieved_files)

    # Chat check
    # ... POST to /api/chat/stream (non-streaming variant) with the query
    # ... collect full response
    # ... check must_contain, must_not_contain
    answer = ...

    return {
        "id": spec["id"],
        "retrieval_hit": retrieval_hit,
        "must_contain_hit": all(c.lower() in answer.lower() for c in spec.get("answer_must_contain", [])),
        "must_not_contain_avoided": all(c.lower() not in answer.lower() for c in spec.get("answer_must_not_contain", [])),
    }

# ... aggregate, save to evals/history/YYYY-MM-DD_HHMMSS.json
# ... compare against previous run, fail exit code if regression >2%
```

### Day 3 — Prompt versioning

Move all system prompts + tool descriptions from Python strings into `prompts/*.md` files. Load at startup.

**File: `prompts/security_expert.md`:**
```markdown
You are a senior cybersecurity engineer running 100% locally on an Apple M4 Pro...
```

**File: `backend/prompts.py`:**
```python
from pathlib import Path
PROMPT_DIR = Path(__file__).parent.parent / "prompts"

def load(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text().strip()
```

Now prompt changes are code diffs → git-tracked → PR-reviewable → CI-tested (eval harness).

### Day 4 — Eval in CI (as a check, not a blocker)

Extend CI workflow:
```yaml
eval:
  needs: test
  if: github.event_name == 'pull_request'
  runs-on: macos-14
  steps:
    - uses: actions/checkout@v4
    # ... start ollama + server in background
    - name: Run evals
      run: .venv/bin/python evals/run.py --compare-baseline
    - name: Upload results
      uses: actions/upload-artifact@v4
      with: {name: eval-report, path: evals/history/latest.json}
    # Post comment on PR with delta vs main
```

### Day 5 — Feedback → digest

Weekly cron (or `scripts/feedback_digest.py`):
- Pull all 👎 responses from the past week
- Group by workspace, model, common substrings
- Output markdown digest: "This week: 12 downvotes on Security Expert. Top themes: (1) …"
- Email or drop into `evals/digests/YYYY-Www.md`

**Week 7 wrap:** evals run against every PR. Prompts are files. Tag `v0.6.0`.

## Week 8 — Metrics + tracing + dashboards

### Day 1 — Prometheus metrics

Install `prometheus-fastapi-instrumentator`.

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, "/metrics", include_in_schema=False)
```

Custom metrics in `backend/metrics.py`:
```python
from prometheus_client import Counter, Histogram, Gauge

chat_requests_total = Counter("studio_chat_requests_total", "Chat requests by model + status", ["model", "status"])
retrieval_latency_seconds = Histogram("studio_retrieval_latency_seconds", "RAG retrieval latency", buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5))
tool_calls_total = Counter("studio_tool_calls_total", "Tool invocations", ["tool", "status"])
feedback_total = Counter("studio_feedback_total", "Feedback by rating", ["rating"])
active_streams = Gauge("studio_active_streams", "Currently-streaming chat requests")
```

Instrument the orchestrator, feedback endpoint, RAG retrieve.

### Day 2 — OpenTelemetry tracing

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
FastAPIInstrumentor.instrument_app(app)
```

Manual spans in orchestrator:
```python
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("rag.retrieve"):
    hits = await rag.retrieve(...)
with tracer.start_as_current_span("model.chat", attributes={"model": model_name}):
    ...
```

### Day 3 — Local Grafana stack

**File: `docker/observability-compose.yml`:**
```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml:ro"]
    ports: ["9090:9090"]
  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
    volumes: ["grafana_data:/var/lib/grafana", "./grafana/dashboards:/var/lib/grafana/dashboards"]
  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yml"]
    volumes: ["./tempo.yml:/etc/tempo.yml:ro"]
    ports: ["4318:4318"]
volumes: {grafana_data: {}}
```

Provisioned dashboards under `docker/grafana/dashboards/*.json`:
- **Overview**: req/s, error rate, p50/p95/p99 latency
- **RAG**: retrieval latency histogram, hit rate over time
- **Models**: TPS by model, cost by model, tokens by workspace
- **Feedback**: 👍/👎 trend, coverage % over time

### Day 4 — Cost tracking

Adapt what cc-callbacks does — record per-request token counts + model → tag with workspace + user. Aggregate daily in a `cost_ledger` table for local reporting.

### Day 5 — Alerting

Grafana alert rules:
- Error rate > 5% for 5 min → notification
- p95 latency > 30 s → notification
- Ollama /api/tags fails 3× in a row → notification
- Feedback negativity > 40% over 20 responses → warning

Route to macOS notification via `terminal-notifier` (local) or Slack webhook (if team). Keep local.

**Week 8 wrap:** open `localhost:3000` → see dashboards. Tag `v0.7.0`.

---

# PHASE 5 — USER EXPERIENCE (Weeks 9–10)

Goal: someone else can pick it up and use it without you.

## Week 9 — First-run wizard + onboarding

### Day 1 — Detection logic

`GET /api/onboarding/status` returns:
```json
{
  "ollama_up": true,
  "models_installed": ["qwen2.5:32b"],
  "recommended_missing": ["nomic-embed-text", "qwen2.5-coder:32b"],
  "workspaces_created": 0,
  "corpus_downloaded": false,
  "auth_bootstrapped": true
}
```

Frontend calls this on load. If any recommended field missing → show wizard overlay.

### Day 2 — Wizard UI

New module `static/js/onboarding.js` — modal steps:
1. **Welcome** + hardware detected (M4 Pro / RAM / GPU cores)
2. **Pick models** — checkboxes for recommended set with sizes + descriptions; pulls in background with progress bars using `/api/models/pull` (new endpoint that streams ollama pull output as SSE)
3. **Curate corpus** — offer to download Security + Coding corpora
4. **Build workspaces** — run `build_expert_workspaces.py` via new endpoint
5. **Done** — quick tour of the UI (annotated tooltips on 5 key elements)

Streams progress via SSE so the user sees "downloading qwen2.5:32b: 43% (8.2/19 GB)".

### Day 3 — Empty-state improvements

Every empty state gets an action:
- No workspaces → "Create your first workspace" CTA
- No conversations → templates gallery
- No models → run first-run wizard
- No files in workspace → drag-drop + URL-fetch + template hint

### Day 4 — Keyboard-first UX

Audit and add shortcuts (visible via `?` overlay):
| Shortcut | Action |
|---|---|
| `⌘K` | Command palette |
| `⌘N` | New conversation |
| `⌘B` | Toggle sidebar |
| `⌘⇧M` | Cycle model |
| `⌘/` | Focus composer |
| `⌘↵` | Send |
| `⌘⇧R` | Regenerate last |
| `?` | Shortcuts help |

Implement in `static/js/keybindings.js`.

### Day 5 — Error recovery UX

Every visible error has a "recover" action:
- Ollama down → "Start Ollama" button (spawns `ollama serve` via tray app or shows brew command)
- Embed model missing → "Pull embed model" one-click
- File upload failed → "Retry" with backoff
- Chat stream cut mid-way → "Resume from last token" (best-effort — resends with `continue: true` marker)

**Week 9 wrap:** brand-new user opens the .app, gets through wizard, has a working expert workspace in <5 min. Tag `v0.8.0`.

## Week 10 — Docs · a11y · mobile · voice

### Day 1 — Docs site (MkDocs Material)

Install `mkdocs mkdocs-material`.

**File: `mkdocs.yml`:**
```yaml
site_name: Local LLM Studio
theme:
  name: material
  palette:
    scheme: slate
    primary: deep purple
  features: [navigation.instant, navigation.sections, search.suggest, content.code.copy]
nav:
  - Home: index.md
  - Get Started:
    - Install: install.md
    - First Run: first-run.md
    - Concepts: concepts.md
  - Workspaces:
    - Building Expert Workspaces: workspaces.md
    - Adding Documents: ingestion.md
    - RAG Quality: rag-tuning.md
  - Tools & Agents:
    - Tool Catalog: tools.md
    - Sandbox: sandbox.md
    - Think Deeply: think-deeply.md
  - Reference:
    - API: api.md
    - Settings: settings.md
    - Architecture: architecture.md
  - Operations:
    - Backups: ops/backups.md
    - Monitoring: ops/monitoring.md
    - Updating: ops/updating.md
```

Write ~15 pages. Screenshots. Autogen API reference from FastAPI's OpenAPI JSON.

Publish to GitHub Pages via CI.

### Day 2 — Accessibility pass

- [ ] Every button has an accessible name (via `aria-label` when text-less, or visible text)
- [ ] Every icon in a text button has `aria-hidden="true"`
- [ ] Focus outline visible on every interactive element (`:focus-visible` styles)
- [ ] Color contrast ≥ 4.5:1 (audit with axe-core browser extension)
- [ ] Keyboard traps eliminated in modals (focus trap that returns on close)
- [ ] SSE events announced to screen readers via `aria-live="polite"` region
- [ ] Skip-to-content link at the top
- [ ] Semantic HTML: `<main>`, `<nav>`, `<article>` for messages
- [ ] Language declared on `<html lang="en">`

Add `axe-core` to Playwright e2e tests — assert no serious violations.

### Day 3 — Mobile-responsive

CSS breakpoints:
- **≥ 1200 px**: current 3-column layout (sidebar + main + artifact drawer)
- **900–1199 px**: sidebar collapses to icon rail; artifact drawer becomes modal
- **< 900 px**: sidebar as hamburger drawer; artifact drawer full-screen; message toolbar collapses to overflow-only

Refactor `.app-container` grid + add media queries. Test on iPad Safari and iPhone (via Chrome devtools emulation).

Add `<meta name="viewport" content="width=device-width, initial-scale=1">` (already there).

### Day 4 — Voice input

Install `whisper.cpp`:
```bash
brew install whisper-cpp
```

**New endpoint `POST /api/audio/transcribe`:**
```python
@app.post("/api/audio/transcribe")
async def transcribe(file: UploadFile = File(...)):
    tmp = save uploaded audio to /tmp
    result = subprocess.run(
        ["whisper-cli", "-m", MODEL_PATH, "-f", tmp, "-otxt", "--no-timestamps"],
        capture_output=True, text=True, timeout=60,
    )
    return {"text": result.stdout.strip()}
```

Frontend: mic button in composer → `MediaRecorder` → POST audio → paste transcript into composer.

Pull whisper model: `curl -L -o models/whisper-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin`.

### Day 5 — Voice output (optional stretch)

Install `piper` TTS. New endpoint `POST /api/audio/tts` → returns audio. Frontend adds 🔊 button on assistant messages.

**Week 10 wrap:** docs live at `<username>.github.io/local-llm-studio`, mobile-usable, voice works. Tag `v0.9.0`.

---

# PHASE 6 — SHIP v1.0 (Weeks 11–12)

## Week 11 — Testing bar + polish

### Day 1 — Coverage push to 60%

Fill the gaps in `pytest --cov`. Focus on `agent_orchestrator` (still complex), `rag` (business-critical), `long_term_memory`.

### Day 2 — Playwright e2e

**File: `tests/e2e/test_flows.spec.ts`:**
- Open app → wizard appears (if fresh) → skip → land on main
- Create conversation → send message → see stream → see done event
- Upload file → see it in workspace files → RAG citation appears in next chat
- Click 👍 on message → verify feedback persisted
- Click Compare → modal opens → run compare → see two answers
- Try slash `/model qwen2.5:32b` → composer clears, toast confirms

Run in CI on merge to main.

### Day 3 — Load test

`locust` or `k6`. Baseline:
- 100 concurrent chats: p95 < 5s to first token, < 30s to done
- 1000 sequential RAG queries: p95 < 500ms
- Sandbox 100 concurrent Python runs: no crashes

Fix hotspots (usually SQLite lock contention → move to Postgres or WAL tuning).

### Day 4 — Bug bash

- Test every code path in `Plan/CAPABILITY_UPGRADES_ROUND_3.md`.
- Try to break the auth (weird cookie values, replay, timing).
- Try to break the sandbox (fork bomb, memory bomb, network).
- Try to break the chunker (empty file, giant file, binary file mislabeled).
- Try to break the compare UI (same model twice, non-existent model, offline model).

### Day 5 — Legal

- [ ] Add `LICENSE` (Apache 2.0 recommended). Header comment in every source file (`Apache 2.0 — see LICENSE`).
- [ ] Add `NOTICE.md`:
  ```
  Local LLM Studio bundles / retrieves the following third-party content:
  - OWASP Cheat Sheet Series — CC-BY-SA 4.0
  - OWASP Top 10 — CC-BY-SA 4.0
  - OWASP ASVS — CC-BY-SA 4.0
  - MITRE ATT&CK — LICENSE-mitre.txt (Terms of Use)
  - CWE — public
  - Rust Book — Apache-2.0 / MIT
  - Python cpython docs — PSF License
  - Go docs — CC-BY-3.0
  - TypeScript Handbook — MIT
  - marked, DOMPurify, highlight.js — see esm.sh imports
  ```
- [ ] Add `PRIVACY.md`: local-first, what leaves the machine and when.
- [ ] `CODE_OF_CONDUCT.md` + `CONTRIBUTING.md` (Contributor Covenant 2.1).
- [ ] `SECURITY.md`: how to report a vulnerability (email + PGP key or GitHub advisory).

## Week 12 — v1.0 release

### Day 1 — Release candidate

- [ ] Bump version to `1.0.0-rc.1`
- [ ] Full changelog written from git log
- [ ] Full README rewrite: 30-second value prop, screenshots, quickstart, feature list
- [ ] Publish RC to GitHub Releases

### Day 2 — Dogfood

Use only the RC for a full day. Note every friction point. Fix P0/P1s.

### Day 3 — External beta

Give 3–5 friends the RC. Watch them install. Fix the top confusions.

### Day 4 — Final polish

- [ ] All README screenshots refreshed
- [ ] Demo video (60 s) recorded
- [ ] GitHub topics + description set
- [ ] Landing page (if Path B/C on the horizon)

### Day 5 — Ship

- [ ] Tag `v1.0.0`
- [ ] Publish signed `.app.zip`, `.dmg`, Docker image
- [ ] Blog post / launch note
- [ ] Choose the next fork:
  - **Continue A:** Native features (voice out, Shortcuts, Finder QuickAction, iCloud sync)
  - **Start B:** Multi-user (Postgres, auth, RBAC, Compose stack for team)
  - **Start D:** Open-source community (marketplace, plugins, docs)

---

# CROSS-CUTTING CONCERNS

## Legal / licensing

**Recommended:** Apache 2.0 for the code — permissive, patent grant, widely accepted.

**Corpus:** the pieces bundled by `curate_corpus.py` retain their upstream licenses. **The important one:** OWASP is CC-BY-SA. If you *ship* a compiled corpus with the app (embedded chunks in the SQLite DB), that DB may be considered a derivative work and must be released under a compatible license. Safe workaround: **don't ship the corpus embeds** — have first-run download and embed on the user's machine. The user's local DB is their own, not distributed.

## Dependency management

- Pin exact versions in `requirements-lock.txt` (generated via `pip freeze`)
- `pyproject.toml` uses loose bounds for library consumers
- Renovate or Dependabot weekly PRs
- Security-only auto-merge, feature updates need review

## Release process

Every release (patch/minor/major):
1. `git checkout -b release/vX.Y.Z`
2. Bump version in `pyproject.toml` + `packaging/updater.py::CURRENT`
3. Update `CHANGELOG.md` (auto-generated from conventional commits: `git cliff` or `standard-version`)
4. Merge PR, tag `vX.Y.Z`, CI publishes Docker image + `.app` bundle
5. Draft GitHub release, paste changelog, attach binaries

## Data-model versioning

Every migration in `migrations/NNNNN_description.sql` is applied in order by yoyo. Never edit an existing migration — always add a new one. Data-loss migrations require an explicit env var opt-in: `STUDIO_ALLOW_DESTRUCTIVE_MIGRATION=1`.

## Backup + disaster recovery

- Nightly `sqlite3 .backup` → gzip → `~/Library/Application Support/LocalLLMStudio/backups/`
- Retention: daily × 30, weekly × 12, monthly × forever
- Monthly restore drill (scripted, cron)
- Corpus is reproducible (`curate_corpus.py`), so not backed up — just tracked in git

## Configuration matrix

Every setting knowable by env var and by `POST /api/settings`. Env wins.

| Setting | Env var | Default | Where used |
|---|---|---|---|
| Data dir | `STUDIO_DATA_DIR` | `~/Library/Application Support/LocalLLMStudio` | config.py |
| DB path | `STUDIO_DB_PATH` | `$DATA/workspace.db` | database.py |
| Ollama host | `OLLAMA_HOST` | `http://127.0.0.1:11434` | ollama_client.py |
| Bind host | `BIND_HOST` | `127.0.0.1` | server.py |
| Session token | `SESSION_TOKEN` | *auto-generated* | auth.py |
| Log level | `LOG_LEVEL` | `INFO` | server.py |
| Embed model | `STUDIO_EMBED_MODEL` | `nomic-embed-text` | rag.py |
| Rerank model | `STUDIO_RERANK_MODEL` | `dolphin3:latest` | rag.py |

## Definition-of-done checklists (per PR)

Every PR must satisfy:
- [ ] All existing tests pass locally
- [ ] New code has tests (or explicit "not tested — reason" note)
- [ ] `ruff check` clean
- [ ] `mypy backend/` clean
- [ ] `CHANGELOG.md` entry if user-visible
- [ ] Docs updated if API/UX changed
- [ ] Screenshots refreshed if UI changed

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Python 3.14 wheel gap | High | Medium | Downgrade to 3.12 for CI + release (already planned wk 2) |
| Ollama business model change | Low | High | Wrap in `ModelProvider` interface (wk 5) — can swap to llama.cpp |
| macOS sandbox-exec removal | Medium | Medium | Docker sandbox in place by wk 4 |
| OWASP CC-BY-SA on corpus binary | High | Medium | Don't ship compiled corpus; user-side ingest only |
| Data corruption on crash mid-ingest | Low | High | Wrap ingest in transaction (already partially — verify) |
| DoS via giant PDF upload | Medium | Medium | Rate limit + upload size cap (wk 3 covers) |
| Prompt-injection exfil via corpus doc | Medium | Low | Prompt-scan on tool results, not just user input |

## Milestones summary

| Week | Tag | Headline |
|---|---|---|
| 2 | v0.2.0 | CI + tests + backups |
| 4 | v0.3.0 | Auth + sandbox + audit trail |
| 5 | v0.4.0 | Docker stack |
| 6 | v0.5.0 | macOS .app + tray + updater |
| 7 | v0.6.0 | Eval harness + prompt versioning |
| 8 | v0.7.0 | Metrics + tracing + Grafana |
| 9 | v0.8.0 | First-run wizard + keyboard UX |
| 10 | v0.9.0 | Docs + a11y + mobile + voice |
| 12 | **v1.0.0** | Ship |

---

# APPENDIX A — All new files this playbook creates

```
.github/workflows/ci.yml
.github/workflows/release.yml
.dockerignore
Dockerfile
docker-compose.yml
docker/sandbox.Dockerfile
docker/observability-compose.yml
docker/prometheus.yml
docker/tempo.yml
docker/grafana/dashboards/*.json
Makefile
CHANGELOG.md
CODE_OF_CONDUCT.md
CONTRIBUTING.md
LICENSE
NOTICE.md
PRIVACY.md
SECURITY.md
mkdocs.yml
docs/**/*.md
tests/conftest.py
tests/backend/test_*.py
tests/e2e/test_flows.spec.ts
evals/README.md
evals/security_expert.jsonl
evals/coding_expert.jsonl
evals/run.py
prompts/security_expert.md
prompts/coding_expert.md
prompts/*.md
scripts/backup_db.sh
scripts/first_run.sh
scripts/feedback_digest.py
packaging/build_app.py
packaging/tray_app.py
packaging/updater.py
packaging/icon.icns
backend/config.py
backend/middleware.py
backend/auth.py
backend/security_headers.py
backend/rate_limit.py
backend/prompt_safety.py
backend/secure_settings.py
backend/audit_log.py
backend/metrics.py
backend/types.py
backend/prompts.py
requirements-lock.txt
```

# APPENDIX B — All new dependencies

```
# runtime
slowapi                    # rate limiting
keyring                    # macOS Keychain
prometheus-fastapi-instrumentator
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-http
opentelemetry-instrumentation-fastapi
rumps                      # macOS menu-bar
pynput                     # global hotkey

# dev
pytest-cov
pytest-asyncio
pytest-httpx
ruff
mypy
pyinstaller
mkdocs
mkdocs-material
locust                     # or k6 (binary)
```

# APPENDIX C — Definition of "professional" done

At v1.0 you should be able to say YES to every one of these:

- [ ] Anyone can install via `docker compose up` or double-click `.app`
- [ ] Every push runs tests + typecheck + lint in CI
- [ ] Coverage ≥ 60% on backend
- [ ] Auth required for every API call
- [ ] Content-Security-Policy header on every response
- [ ] Rate-limited
- [ ] Prompt-injection heuristics running
- [ ] Python execution runs in Docker sandbox (not sandbox-exec)
- [ ] Every write action + tool execution goes to audit log
- [ ] Nightly backups + monthly restore drill
- [ ] Prometheus metrics + Grafana dashboards
- [ ] OpenTelemetry traces
- [ ] Eval harness runs on every PR, blocks regressions
- [ ] Prompts are files, git-tracked, PR-reviewable
- [ ] Fresh user reaches working chat in <5 min
- [ ] Docs site published + linked from README
- [ ] Keyboard-first UX
- [ ] axe-core reports zero serious a11y violations
- [ ] Works on iPad Safari
- [ ] Voice input works
- [ ] LICENSE + NOTICE + PRIVACY + SECURITY + CoC files present
- [ ] Semver + changelog + signed release binaries


