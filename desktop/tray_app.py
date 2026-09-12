"""
macOS menu-bar tray app for Local LLM Studio.

Runs uvicorn as a subprocess, waits until /api/health returns 200, then
sits in the menu bar offering: open studio, restart server, view logs,
check for updates, quit.

`rumps` and `pynput` are imported lazily so this module can be imported
on non-macOS platforms (or in CI) to unit-test the plain-Python helpers
below without pulling in Objective-C bridges.

Entry point used by PyInstaller: __main__ block at the bottom.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

SERVER_URL = "http://127.0.0.1:8080"
HEALTH_URL = f"{SERVER_URL}/api/health"
READY_TIMEOUT_S = 30
LOG_PATH = Path.home() / "Library" / "Logs" / "LocalLLMStudio.log"

# When running as a PyInstaller-frozen bundle the working dir is somewhere
# under Contents/Resources; `_MEIPASS` (set by PyInstaller) points to it.
BUNDLE_ROOT: Path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

# User data (SQLite, uploads, artifacts, token) lives outside the bundle
# so upgrades don't wipe state.
DATA_DIR = Path.home() / "Library" / "Application Support" / "LocalLLMStudio"

log = logging.getLogger("studio.tray")


def build_server_env() -> dict[str, str]:
    """Env vars we set before spawning uvicorn. Kept as a pure function so
    it's unit-testable without spinning up the tray."""
    env = os.environ.copy()
    env["BIND_HOST"] = "127.0.0.1"
    env["BIND_PORT"] = "8080"
    env["STUDIO_DATA_DIR"] = str(DATA_DIR)
    env["STUDIO_DB_PATH"] = str(DATA_DIR / "workspace.db")
    env["STUDIO_UPLOAD_DIR"] = str(DATA_DIR / "uploads")
    env["STUDIO_ARTIFACTS_DIR"] = str(DATA_DIR / "artifacts")
    env["STUDIO_TOKEN_FILE"] = str(DATA_DIR / "token")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def server_command() -> list[str]:
    """Argv used to spawn uvicorn. Frozen bundles ship a bundled interpreter
    (`sys.executable`), so this works both in dev and in the .app."""
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]


def wait_for_health(url: str = HEALTH_URL, timeout_s: int = READY_TIMEOUT_S) -> bool:
    """Poll /api/health once per second up to timeout. Returns True on first
    2xx, False if the timeout elapses. Pure helper so tests can drive it
    against any URL."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.5)
            if 200 <= r.status_code < 300:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


class _ServerProcess:
    """Owns the uvicorn subprocess. Split out so the tray class stays thin
    and this piece is testable without rumps installed."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        logf = open(LOG_PATH, "ab", buffering=0)  # noqa: SIM115 — kept open for the subprocess's lifetime
        self.proc = subprocess.Popen(
            server_command(),
            env=build_server_env(),
            cwd=str(BUNDLE_ROOT),
            stdout=logf,
            stderr=logf,
        )
        atexit.register(self.stop)

    def stop(self) -> None:
        if not self.proc:
            return
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def restart(self) -> None:
        self.stop()
        self.start()

    @property
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def _run_tray() -> None:
    """Import and start rumps. Kept in its own function so importing this
    module doesn't require rumps (it's macOS-only + heavy PyObjC bridge)."""
    import rumps

    from desktop.hotkey import register_hotkey

    server = _ServerProcess()
    server.start()
    register_hotkey(SERVER_URL)

    class Studio(rumps.App):
        def __init__(self) -> None:
            super().__init__("Studio", quit_button=None)
            self.title = "Studio…"  # temporary while waiting for readiness
            self.menu = ["Open Studio", "Restart Server", "View Logs", None, "Quit"]
            threading.Thread(target=self._await_ready, daemon=True).start()

        def _await_ready(self) -> None:
            ok = wait_for_health()
            self.title = "Studio" if ok else "Studio ⚠"

        @rumps.clicked("Open Studio")
        def open_studio(self, _: object) -> None:
            webbrowser.open(SERVER_URL)

        @rumps.clicked("Restart Server")
        def restart(self, _: object) -> None:
            server.restart()
            self.title = "Studio…"
            threading.Thread(target=self._await_ready, daemon=True).start()

        @rumps.clicked("View Logs")
        def view_logs(self, _: object) -> None:
            subprocess.Popen(["open", "-a", "Console", str(LOG_PATH)])

        @rumps.clicked("Quit")
        def quit_app(self, _: object) -> None:
            server.stop()
            rumps.quit_application()

    Studio().run()


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit(f"tray app is macOS-only (running on {sys.platform})")
    _run_tray()
