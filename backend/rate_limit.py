"""Per-endpoint rate limiting via slowapi.

Local single-user app doesn't need aggressive limits — we're guarding
against runaway scripts and browser-tab loops, not deliberate abuse.
Limits are per-source-IP; on localhost that's effectively 'per user'.

Default is generous (120 req/min); hot endpoints (chat, sandbox, upload)
get their own tighter budgets.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import CONFIG

limiter = Limiter(key_func=get_remote_address, default_limits=[CONFIG.rate_limit_default])

# Named limits so endpoint decorators stay readable.
LIMIT_CHAT_STREAM = CONFIG.rate_limit_chat
LIMIT_SANDBOX = CONFIG.rate_limit_sandbox
LIMIT_UPLOAD = CONFIG.rate_limit_upload
LIMIT_COMPARE = CONFIG.rate_limit_compare
