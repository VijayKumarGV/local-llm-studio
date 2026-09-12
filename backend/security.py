"""
Security & Permissions Sandbox for Local LLM Studio.
Enforces strict filesystem isolation, path traversal guards, subprocess resource limits,
and configurable tool permissions. On macOS, wraps Python execution in `sandbox-exec`
with a deny-by-default profile that blocks network and disallows writes outside the
scratch directory.
"""

import os
import platform
import shutil
import subprocess
import sys
from typing import Any

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_STDOUT_BYTES = 50 * 1024  # 50 KB max stdout/stderr

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


def run_sandboxed_python(code: str, timeout_seconds: int = 15) -> dict[str, Any]:
    """
    Executes Python code in an isolated subprocess with strict timeouts, output
    capping, and — on macOS — a `sandbox-exec` deny-by-default profile that
    blocks network and disallows writes outside the scratch directory.
    """
    scratch_dir = os.path.join(WORKSPACE_DIR, "backend", "uploads", "scratch")
    os.makedirs(scratch_dir, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HOME"] = scratch_dir  # deny access to real $HOME/.ssh etc.

    inner_cmd = [sys.executable, "-I", "-c", code]

    if _ON_MACOS and SANDBOX_EXEC:
        cmd = [SANDBOX_EXEC, "-p", _MACOS_SANDBOX_PROFILE, "-D", f"SCRATCH={scratch_dir}"] + inner_cmd
    else:
        cmd = inner_cmd

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
            if len(stdout) > MAX_STDOUT_BYTES:
                stdout = stdout[:MAX_STDOUT_BYTES] + "\n[Output truncated: Exceeded 50KB limit]"
            if len(stderr) > MAX_STDOUT_BYTES:
                stderr = stderr[:MAX_STDOUT_BYTES] + "\n[Output truncated: Exceeded 50KB limit]"
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "sandboxed": bool(_ON_MACOS and SANDBOX_EXEC),
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"status": "timeout", "error": f"Execution timed out after {timeout_seconds} seconds."}
    except Exception as e:
        return {"status": "error", "error": str(e)}


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
