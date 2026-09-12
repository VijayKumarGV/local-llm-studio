"""Strip the sandbox's proxy env before running eval tests — pytest_httpx
can't intercept requests that go through an httpx proxy transport."""

from __future__ import annotations

import pytest

_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "FTP_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "ftp_proxy",
)


@pytest.fixture(autouse=True)
def _no_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in _PROXY_VARS:
        monkeypatch.delenv(v, raising=False)
