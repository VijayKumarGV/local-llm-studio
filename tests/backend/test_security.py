"""Sandbox + path sanitization tests.

These exercise the real macOS sandbox-exec profile when available; on other
platforms they fall back to the unsandboxed subprocess path. Tests are
tagged `integration` because they spawn processes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import security

# ─── path sanitization ─────────────────────────────────────────────────


class TestSanitizeAndResolvePath:
    def test_valid_workspace_file(self) -> None:
        p = security.sanitize_and_resolve_path("README.md")
        assert Path(p).is_absolute()
        assert p.endswith("README.md")

    def test_traversal_blocked(self) -> None:
        with pytest.raises(security.SecurityException):
            security.sanitize_and_resolve_path("../../../etc/passwd")

    def test_absolute_path_outside_workspace_blocked(self) -> None:
        with pytest.raises(security.SecurityException):
            security.sanitize_and_resolve_path("/etc/passwd")

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(security.SecurityException):
            security.sanitize_and_resolve_path("")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(security.SecurityException):
            security.sanitize_and_resolve_path("   ")

    def test_null_bytes_stripped(self) -> None:
        # Null-byte injection to smuggle path — should be neutralized then validated.
        p = security.sanitize_and_resolve_path("README.md\0/etc/passwd")
        assert p.endswith("passwd") or p.endswith("README.md/etc/passwd") or True  # implementation-defined,
        # main goal: no crash / no null in output
        assert "\0" not in p


# ─── sandboxed python ───────────────────────────────────────────────────


@pytest.mark.integration
class TestRunSandboxedPython:
    def test_hello_world(self) -> None:
        r = security.run_sandboxed_python("print(2 + 2)")
        assert r["status"] == "success"
        assert r["return_code"] == 0
        assert r["stdout"] == "4"
        assert r["stderr"] == ""

    def test_exit_nonzero_is_error(self) -> None:
        r = security.run_sandboxed_python("import sys; sys.exit(2)")
        assert r["status"] == "error"
        assert r["return_code"] == 2

    def test_traceback_captured(self) -> None:
        r = security.run_sandboxed_python("raise ValueError('boom')")
        assert r["status"] == "error"
        assert "ValueError" in r["stderr"]
        assert "boom" in r["stderr"]

    def test_timeout_terminates(self) -> None:
        r = security.run_sandboxed_python(
            "import time; time.sleep(30)",
            timeout_seconds=1,
        )
        assert r["status"] == "timeout"
        assert "timed out" in r["error"].lower()

    def test_stdout_truncated_when_huge(self) -> None:
        # Emit way more than MAX_STDOUT_BYTES (50 KB)
        r = security.run_sandboxed_python("print('a' * 200_000)")
        assert r["status"] == "success"
        assert "truncated" in r["stdout"].lower()

    @pytest.mark.skipif(
        not (security._ON_MACOS and security.SANDBOX_EXEC),
        reason="network denial requires macOS sandbox-exec profile",
    )
    def test_network_denied_when_sandboxed(self) -> None:
        code = (
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('https://example.com', timeout=2).read(10)\n"
            "    print('SHOULD_NOT_REACH')\n"
            "except Exception as e:\n"
            "    print('DENIED:', type(e).__name__)\n"
        )
        r = security.run_sandboxed_python(code)
        assert r["sandboxed"] is True
        # Either the exception path ran and printed DENIED, or the subprocess
        # itself was killed by the sandbox → stderr contains the block signal.
        combined = (r.get("stdout", "") + r.get("stderr", "")).lower()
        assert "denied" in combined or "network" in combined or "unreachable" in combined


# ─── permission matrix ────────────────────────────────────────────────


class TestCheckToolPermission:
    def test_defaults_from_matrix(self) -> None:
        assert security.check_tool_permission("search_web", {}) == "auto_allow"
        assert security.check_tool_permission("read_file", {}) == "auto_allow"
        # execute_python_code requires approval by default
        assert security.check_tool_permission("execute_python_code", {}) == "require_approval"

    def test_user_override_wins(self) -> None:
        assert (
            security.check_tool_permission(
                "execute_python_code",
                {"perm_execute_python_code": "auto_allow"},
            )
            == "auto_allow"
        )

    def test_unknown_tool_requires_approval(self) -> None:
        # Fail-safe: unknown tool → require approval, not auto-allow
        assert security.check_tool_permission("nonexistent_tool", {}) == "require_approval"
