"""
Async HTTP client for Ollama, shared across the app.
Reuses a single httpx.AsyncClient so connections are pooled and streaming
never blocks the event loop.
"""

import os

import httpx

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

_client: httpx.AsyncClient | None = None


def get_ollama_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=OLLAMA_HOST,
            timeout=httpx.Timeout(connect=5.0, read=None, write=30.0, pool=5.0),
        )
    return _client


async def close_ollama_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
