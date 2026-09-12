"""E2E fixtures — boot uvicorn in a background thread against a temp
DB with ollama pointed at a black-hole URL, then run Playwright against
it. Kept intentionally minimal — every test here should be able to run
without ollama or any external service."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

SESSION_TOKEN = "e2e-test-token"


def _pick_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _UvicornThread(threading.Thread):
    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(daemon=True)
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        self.server.run()


@pytest.fixture(scope="session")
def studio_server(tmp_path_factory: pytest.TempPathFactory):
    """Boot the FastAPI app on a random localhost port. Yields the base URL."""
    port = _pick_port()
    data = tmp_path_factory.mktemp("e2e-data")

    import os

    os.environ["SESSION_TOKEN"] = SESSION_TOKEN
    os.environ["STUDIO_DATA_DIR"] = str(data)
    os.environ["STUDIO_DB_PATH"] = str(data / "workspace.db")
    os.environ["STUDIO_UPLOAD_DIR"] = str(data / "uploads")
    os.environ["STUDIO_ARTIFACTS_DIR"] = str(data / "artifacts")
    os.environ["STUDIO_TOKEN_FILE"] = str(data / "token")
    # Point ollama at a port nothing's listening on — endpoints that need
    # ollama will fail fast; the wizard tolerates the outage.
    os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{_pick_port()}"

    from backend import auth, config

    config.reload()
    auth._TOKEN = None

    cfg = uvicorn.Config(
        "backend.server:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
        reload=False,
    )
    server_thread = _UvicornThread(cfg)
    server_thread.start()

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=1.0) as c:
                r = c.get(f"{base}/api/health")
                if r.status_code == 200:
                    break
        except (httpx.HTTPError, OSError):
            time.sleep(0.15)
    else:
        raise RuntimeError(f"studio server never came up on {base}")

    yield base

    server_thread.server.should_exit = True
    server_thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(studio_server: str) -> str:
    """pytest-playwright's `page` fixture reads this to know where to go."""
    return studio_server


@pytest.fixture
def authed_page(page, studio_server):
    """Playwright page pre-authenticated via cookie. Skips the /auth
    bootstrap redirect so tests can navigate straight to `/`."""
    page.context.add_cookies(
        [
            {
                "name": "studio_token",
                "value": SESSION_TOKEN,
                "url": studio_server,
            }
        ]
    )
    return page
