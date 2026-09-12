"""HTTP security headers middleware.

Applied to every response, including error responses. Trades convenience for
defense-in-depth: even a page-level XSS bug can't easily talk to a third-party
origin, get iframed, or run inline scripts we didn't intend.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response

# CSP notes:
# - script-src includes https://esm.sh because the frontend loads marked,
#   highlight.js, DOMPurify from there as ES modules.
# - style-src keeps 'unsafe-inline' because hljs themes + a few inline
#   style="…" attributes in the SPA. Remove once we self-host + audit.
# - connect-src is 'self' + Ollama's localhost address (frontend never
#   talks to Ollama directly, but leaves the door open for a future
#   HMR / debug tool without needing another CSP tweak).
# - img-src 'self' data: blob: — we render base64 image previews for
#   attachments and blob URLs from marked's rendered content.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://esm.sh; "
    "style-src 'self' 'unsafe-inline' https://esm.sh; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data: https://esm.sh; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), interest-cohort=()",
}


async def security_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    resp = await call_next(request)
    for k, v in _HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp
