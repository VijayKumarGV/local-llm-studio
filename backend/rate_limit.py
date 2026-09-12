"""Per-endpoint rate limiting via slowapi.

Local single-user app doesn't need aggressive limits — we're guarding
against runaway scripts and browser-tab loops, not deliberate abuse.
Limits are per-source-IP; on localhost that's effectively 'per user'.

Default is generous (120 req/min); hot endpoints (chat, sandbox, upload)
get their own tighter budgets.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Env override so tests can bump limits high enough not to interfere.
_DEFAULT = os.environ.get("STUDIO_RATE_LIMIT_DEFAULT", "120/minute")

limiter = Limiter(key_func=get_remote_address, default_limits=[_DEFAULT])

# Named limits so endpoint decorators stay readable.
LIMIT_CHAT_STREAM = os.environ.get("STUDIO_RATE_LIMIT_CHAT", "20/minute")
LIMIT_SANDBOX = os.environ.get("STUDIO_RATE_LIMIT_SANDBOX", "30/minute")
LIMIT_UPLOAD = os.environ.get("STUDIO_RATE_LIMIT_UPLOAD", "60/hour")
LIMIT_COMPARE = os.environ.get("STUDIO_RATE_LIMIT_COMPARE", "10/minute")
