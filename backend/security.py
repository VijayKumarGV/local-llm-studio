"""
Security & Permissions Sandbox for Local LLM Studio.

Enforces strict filesystem isolation, path traversal guards, subprocess
resource limits, and configurable tool permissions.

Python execution goes through a layered sandbox — preference order:

  1. **Docker** (portable, strongest isolation): --network=none, read-only
     rootfs, capped memory + CPU + pids, cap-drop=ALL. Requires Docker
     Desktop / docker daemon. Preferred everywhere it's available.
  2. **macOS sandbox-exec** (Apple-native, deprecated but still works):
     deny-by-default profile blocking network + writes outside scratch.
  3. **Raw subprocess** (LAST RESORT — no isolation): only if the caller
     opts in via `STUDIO_ALLOW_UNSANDBOXED=1`. Logs a warning.

Selection is dynamic per-call so the user can install Docker later without
restarting.
"""

import logging
import os
import platform
import shutil
import subprocess
import sys
from typing import Any

log = logging.getLogger("studio.security")

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_STDOUT_BYTES = 50 * 1024  # 50 KB max stdout/stderr
SANDBOX_IMAGE = os.environ.get("STUDIO_SANDBOX_IMAGE", "studio-sandbox:latest")

# macOS sandbox-exec profile: deny-by-default, allow read of stdlib and
# read/write only under the scratch dir passed via parameter.
_MACOS_SANDBOX_PROFILE = """
(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm)
(allow file-read*)
(deny network*)
(allow file-write*
    (subpath (param "SCRATCH"))
    (literal "/dev/null")
    (literal "/dev/dtracehelper"))
"""

SANDBOX_EXEC = shutil.which("sandbox-exec")
_ON_MACOS = platform.system() == "Darwin"


class SecurityException(Exception):
    pass


# ==========================================
# 1. STRICT PATH SANITIZATION
# ==========================================


def sanitize_and_resolve_path(target_path: str, base_dir: str = WORKSPACE_DIR) -> str:
    """
    Ensure the resolved path is strictly contained within base_dir.
    Guards against:
    - Path traversal attacks (../, ..\\)
    - Absolute path escapes (e.g. C:\\Windows)
    - Symlink escapes
    """
    if not target_path or not target_path.strip():
        raise SecurityException("Empty path provided.")

    # Remove null bytes
    clean_path = target_path.replace("\0", "").strip()

    # Join with base directory if relative
    if not os.path.isabs(clean_path):
        resolved = os.path.abspath(os.path.join(base_dir, clean_path))
    else:
        resolved = os.path.abspath(clean_path)

    # Resolve symlinks to their real target
    try:
        real_target = os.path.realpath(resolved)
        real_base = os.path.realpath(base_dir)
    except Exception as e:
        raise SecurityException(f"Failed to resolve path: {e}") from e

    # Check common prefix
    common = os.path.commonpath([real_target, real_base])
    if common != real_base:
        raise SecurityException(f"Access Denied: Path '{target_path}' resolves outside the approved workspace.")

    return real_target


# ==========================================
# 2. PYTHON EXECUTION SANDBOX
# ==========================================


def _docker_available() -> bool:
    """True iff the docker CLI exists AND the daemon responds. Checked
    per-call so the user can install/start Docker without restarting."""
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def _sandbox_kind() -> str:
    """Return the sandbox backend that will be used: 'docker' | 'sandbox-exec'
    | 'unsandboxed'. Callers can log this for auditability."""
    if _docker_available():
        return "docker"
    if _ON_MACOS and SANDBOX_EXEC:
        return "sandbox-exec"
    if os.environ.get("STUDIO_ALLOW_UNSANDBOXED"):
        return "unsandboxed"
    return "unavailable"


def _cap_output(text: str) -> str:
    if len(text) > MAX_STDOUT_BYTES:
        return text[:MAX_STDOUT_BYTES] + "\n[Output truncated: Exceeded 50KB limit]"
    return text


def _run_in_docker(code: str, timeout_seconds: int, scratch_dir: str) -> dict[str, Any]:
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:size=64m,exec",
        "--memory=256m",
        "--cpus=1",
        "--pids-limit=64",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--workdir=/work",
        SANDBOX_IMAGE,
        "python",
        "-I",
        "-c",
        code,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "stdout": _cap_output(stdout).strip(),
                "stderr": _cap_output(stderr).strip(),
                "sandboxed": True,
                "sandbox_kind": "docker",
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            subprocess.run(["docker", "ps", "-q", "--filter", f"ancestor={SANDBOX_IMAGE}"], capture_output=True)
            return {"status": "timeout", "error": f"Docker sandbox timed out after {timeout_seconds}s"}
    except OSError as e:
        return {"status": "error", "error": f"docker invocation failed: {e}"}


def _run_in_sandbox_exec(code: str, timeout_seconds: int, scratch_dir: str) -> dict[str, Any]:
    # Caller (_sandbox_kind) already verified SANDBOX_EXEC is not None.
    assert SANDBOX_EXEC is not None, "sandbox-exec not available"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HOME"] = scratch_dir
    cmd: list[str] = [
        SANDBOX_EXEC,
        "-p",
        _MACOS_SANDBOX_PROFILE,
        "-D",
        f"SCRATCH={scratch_dir}",
        sys.executable,
        "-I",
        "-c",
        code,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=scratch_dir,
            env=env,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "stdout": _cap_output(stdout).strip(),
                "stderr": _cap_output(stderr).strip(),
                "sandboxed": True,
                "sandbox_kind": "sandbox-exec",
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"status": "timeout", "error": f"sandbox-exec timed out after {timeout_seconds}s"}
    except OSError as e:
        return {"status": "error", "error": str(e)}


def _run_unsandboxed(code: str, timeout_seconds: int, scratch_dir: str) -> dict[str, Any]:
    log.warning("running code UNSANDBOXED (STUDIO_ALLOW_UNSANDBOXED=1)")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(
            [sys.executable, "-I", "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=scratch_dir,
            env=env,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "stdout": _cap_output(stdout).strip(),
                "stderr": _cap_output(stderr).strip(),
                "sandboxed": False,
                "sandbox_kind": "unsandboxed",
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"status": "timeout", "error": f"unsandboxed run timed out after {timeout_seconds}s"}
    except OSError as e:
        return {"status": "error", "error": str(e)}


def run_sandboxed_python(code: str, timeout_seconds: int = 15) -> dict[str, Any]:
    """
    Executes Python code inside the strongest sandbox available:
    Docker → macOS sandbox-exec → unsandboxed (only if STUDIO_ALLOW_UNSANDBOXED=1).
    """
    scratch_dir = os.path.join(WORKSPACE_DIR, "backend", "uploads", "scratch")
    os.makedirs(scratch_dir, exist_ok=True)

    kind = _sandbox_kind()
    if kind == "docker":
        return _run_in_docker(code, timeout_seconds, scratch_dir)
    if kind == "sandbox-exec":
        return _run_in_sandbox_exec(code, timeout_seconds, scratch_dir)
    if kind == "unsandboxed":
        return _run_unsandboxed(code, timeout_seconds, scratch_dir)
    return {
        "status": "error",
        "error": (
            "no sandbox backend available. Install Docker Desktop, or on macOS set "
            "STUDIO_ALLOW_UNSANDBOXED=1 to run without isolation (NOT recommended)."
        ),
        "sandboxed": False,
        "sandbox_kind": "unavailable",
    }


# ==========================================
# 3. TOOL PERMISSION MATRIX
# ==========================================

# Permission levels: "auto_allow", "require_approval", "disabled"
DEFAULT_TOOL_PERMISSIONS = {
    "search_web": "auto_allow",
    "read_file": "auto_allow",
    "list_files": "auto_allow",
    "execute_python_code": "require_approval",  # Safe by default: requires human approval
    "create_artifact": "auto_allow",
}


def check_tool_permission(tool_name: str, user_settings: dict[str, str]) -> str:
    """Returns 'auto_allow', 'require_approval', or 'disabled'."""
    setting_key = f"perm_{tool_name}"
    return user_settings.get(setting_key, DEFAULT_TOOL_PERMISSIONS.get(tool_name, "require_approval"))
