"""Bearer-token authentication.

Single-user, but non-trivially blocks passers-by at your desk and hardens
against CSRF-style cross-tab attacks.

Token resolution order:
    1. `SESSION_TOKEN` env var
    2. `~/Library/Application Support/LocalLLMStudio/token` file
    3. Auto-generated on first run and written to the file above

The browser bootstraps the token via `GET /auth?token=<t>` which sets a
same-site strict cookie. Subsequent requests are authenticated by that
cookie *or* an `Authorization: Bearer <t>` header (for CLI callers).

Endpoints that don't require auth: `/`, `/auth`, `/api/health`, `/static/*`,
`/favicon.ico`.
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request
from starlette.responses import JSONResponse, Response

from backend.config import CONFIG

log = logging.getLogger("studio.auth")

COOKIE_NAME = "studio_token"

# `/metrics` is public: the server binds to 127.0.0.1 by default, so
# access is already gated at the network level, and a local Prometheus
# scraper doesn't have (or want) a session cookie.
_UNAUTHED_PREFIXES = ("/api/health", "/auth", "/static", "/favicon")
_UNAUTHED_PATHS = {"/", "/metrics"}

_TOKEN: str | None = None


def _token_file() -> Path:
    """Where to persist the auto-generated token. Env override wins over
    the CONFIG default so tests can monkey-patch env without a reload."""
    import os as _os

    override = _os.environ.get("STUDIO_TOKEN_FILE")
    if override:
        return Path(override)
    return CONFIG.session_token_file


def load_or_create_token() -> str:
    """Resolve the active session token, generating + persisting one on first run."""
    global _TOKEN
    if _TOKEN:
        return _TOKEN

    # Read env first so tests that monkeypatch don't need to reload CONFIG.
    import os as _os

    env = _os.environ.get("SESSION_TOKEN") or CONFIG.session_token_env
    if env:
        _TOKEN = env
        return _TOKEN

    path = _token_file()
    if path.exists():
        _TOKEN = path.read_text().strip()
        if _TOKEN:
            return _TOKEN

    _TOKEN = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TOKEN)
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    log.info("first-run session token generated at %s", path)
    log.info("bootstrap URL: http://127.0.0.1:8080/auth?token=%s", _TOKEN)
    return _TOKEN


def reset_token_cache() -> None:
    """Test-only helper: forget the in-memory cached token."""
    global _TOKEN
    _TOKEN = None


def _constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _is_public_path(path: str) -> bool:
    if path in _UNAUTHED_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _UNAUTHED_PREFIXES)


def _extract_presented_token(request: Request) -> str:
    """Pull the token from cookie or Authorization: Bearer header."""
    cookie = request.cookies.get(COOKIE_NAME) or ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return cookie


async def auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if _is_public_path(request.url.path):
        return await call_next(request)

    expected = load_or_create_token()
    presented = _extract_presented_token(request)
    if not presented or not _constant_eq(presented, expected):
        return JSONResponse(
            {"error": "unauthorized", "hint": "GET /auth?token=<token> to bootstrap"},
            status_code=401,
        )
    return await call_next(request)
