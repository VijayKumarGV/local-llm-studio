"""Local fixtures for the desktop-package tests.

The dev sandbox exports HTTP(S)_PROXY / ALL_PROXY env vars pointing at
localhost SOCKS/HTTP proxies. httpx picks those up by default, which
breaks pytest_httpx interception (a proxy transport isn't the one
pytest_httpx patches). Strip them for the duration of these tests so
network is fully mocked.
"""

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
