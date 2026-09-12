"""Per-request middleware: request_id + latency + structured log line.

Every incoming request gets a short UUID that:
  1. Is exposed to clients via the X-Request-ID response header.
  2. Is threaded through every log line via a `contextvars` filter.
  3. Can be echoed back by the client in the same header on retry so we
     can correlate.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

log = logging.getLogger("studio.request")


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:12]
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        dur_ms = (time.perf_counter() - start) * 1000
        log.info(
            "%s %s → %s in %.1fms",
            request.method,
            request.url.path,
            status,
            dur_ms,
        )
        request_id_var.reset(token)


class RequestIdFilter(logging.Filter):
    """Injects request_id from the ContextVar into every log record so the
    root formatter can render [%(request_id)s]."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True
