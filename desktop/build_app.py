"""
Build a standalone macOS .app that bundles the server + assets + venv.

Usage:
    .venv/bin/python desktop/build_app.py

Outputs:
    dist/LocalLLMStudio.app     — double-clickable bundle
    build/                      — PyInstaller intermediate artifacts (safe to delete)

Notes
-----
* Requires PyInstaller (see desktop/requirements.txt).
* The icon file `desktop/icon.icns` is optional — the build proceeds
  without it (PyInstaller falls back to the generic app icon). Drop your
  own .icns in that path to embrand the bundle.
* The tray app spawns uvicorn as a subprocess against the bundled
  backend/. Data (SQLite, uploads, artifacts, token) lives in
  ~/Library/Application Support/LocalLLMStudio/ so an app upgrade doesn't
  wipe user state.
* Not signed / not notarized — see `make notarize` for that step.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "desktop" / "icon.icns"
ENTRYPOINT = ROOT / "desktop" / "tray_app.py"


def build() -> None:
    import PyInstaller.__main__

    args = [
        "--name=LocalLLMStudio",
        "--windowed",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--osx-bundle-identifier=com.avishwakarma.local-llm-studio",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build'}",
        f"--specpath={ROOT / 'build'}",
        # bundled data (paths are `src:dest` inside the bundle)
        f"--add-data={ROOT / 'backend'}:backend",
        f"--add-data={ROOT / 'static'}:static",
        f"--add-data={ROOT / 'migrations'}:migrations",
        f"--add-data={ROOT / 'scripts'}:scripts",
        f"--add-data={ROOT / 'prompts'}:prompts",
        # uvicorn's dynamic imports PyInstaller misses without hints
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=uvicorn.lifespan.off",
        "--hidden-import=uvicorn.protocols.http.h11_impl",
        "--hidden-import=uvicorn.protocols.http.httptools_impl",
        "--hidden-import=uvicorn.protocols.websockets.wsproto_impl",
        "--hidden-import=uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=backend.server",
    ]
    if ICON.is_file():
        args.append(f"--icon={ICON}")
    else:
        print(f"[build] no icon at {ICON}; bundle will use the default app icon", flush=True)
    args.append(str(ENTRYPOINT))

    print(f"[build] pyinstaller args: {' '.join(args)}", flush=True)
    PyInstaller.__main__.run(args)
    app = ROOT / "dist" / "LocalLLMStudio.app"
    if app.exists():
        print(f"[build] built {app}")
    else:
        raise SystemExit("[build] .app did not appear at expected path")


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit(f"[build] macOS-only build script; refusing to run on {sys.platform}")
    build()
