"""Unit tests for the pure-Python helpers in packaging.tray_app.

We don't touch rumps here — that lives inside `_run_tray()` and is only
imported when the tray is actually launched on macOS.
"""

from __future__ import annotations

import sys

import pytest
from pytest_httpx import HTTPXMock

from desktop import tray_app


class TestBuildServerEnv:
    def test_sets_bind_host_to_loopback(self) -> None:
        env = tray_app.build_server_env()
        assert env["BIND_HOST"] == "127.0.0.1"
        assert env["BIND_PORT"] == "8080"

    def test_data_paths_all_under_data_dir(self) -> None:
        env = tray_app.build_server_env()
        for key in ("STUDIO_DB_PATH", "STUDIO_UPLOAD_DIR", "STUDIO_ARTIFACTS_DIR", "STUDIO_TOKEN_FILE"):
            assert env[key].startswith(env["STUDIO_DATA_DIR"]), key

    def test_inherits_from_process_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STUDIO_TRAY_TEST_MARKER", "yes")
        env = tray_app.build_server_env()
        assert env["STUDIO_TRAY_TEST_MARKER"] == "yes"


class TestServerCommand:
    def test_first_arg_is_current_python(self) -> None:
        assert tray_app.server_command()[0] == sys.executable

    def test_binds_to_loopback(self) -> None:
        cmd = tray_app.server_command()
        assert "--host" in cmd
        assert cmd[cmd.index("--host") + 1] == "127.0.0.1"


class TestWaitForHealth:
    def test_returns_true_on_first_200(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url="http://127.0.0.1:9/health", status_code=200)
        assert tray_app.wait_for_health("http://127.0.0.1:9/health", timeout_s=2)

    def test_returns_false_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No httpx_mock registration → all requests raise; wait_for_health
        # should sit through its budget then return False.
        def _fast_sleep(_s: float) -> None:
            pass

        monkeypatch.setattr(tray_app.time, "sleep", _fast_sleep)

        class _FakeClock:
            def __init__(self) -> None:
                self.t = 0.0

            def __call__(self) -> float:
                self.t += 0.6
                return self.t

        monkeypatch.setattr(tray_app.time, "monotonic", _FakeClock())
        assert not tray_app.wait_for_health("http://127.0.0.1:65535/nope", timeout_s=2)
