# macOS `.app` packaging

This directory contains everything needed to ship Local LLM Studio as a
double-clickable macOS app: PyInstaller build, menu-bar tray, global
hotkey, update checker, and release-automation glue.

The runtime venv doesn't need any of these deps — install them only when
you're building a bundle:

```sh
pip install -r desktop/requirements.txt
```

## Local build

```sh
make bundle        # → dist/LocalLLMStudio.app  (unsigned, no notarization)
open dist/LocalLLMStudio.app
```

First launch triggers macOS Gatekeeper because the app is unsigned;
right-click → **Open** to bypass for development. For distribution you
must sign + notarize (below).

Data (SQLite DB, uploads, artifacts, auth token) lives in
`~/Library/Application Support/LocalLLMStudio/` so upgrading the app
never wipes user state.

## Signing + notarization

**One-time setup** — enroll in the Apple Developer Program ($99/year),
create a *Developer ID Application* certificate in Xcode → Settings →
Accounts, and generate an *app-specific password* at
https://appleid.apple.com. Export the cert as `.p12`.

**Env vars** (`make sign` / `make notarize`):

| Var                     | Example                                                        |
| ----------------------- | -------------------------------------------------------------- |
| `APPLE_DEV_ID`          | `"Developer ID Application: Your Name (ABCDE12345)"`           |
| `APPLE_ID`              | `you@example.com`                                              |
| `APPLE_TEAM_ID`         | `ABCDE12345`                                                   |
| `APPLE_PASSWORD`        | app-specific password from appleid.apple.com                   |

Then:

```sh
make sign notarize
```

## CI release

`.github/workflows/release.yml` runs the same pipeline on `macos-14`
whenever a `v*.*.*` tag is pushed. Configure these repo secrets
(**Settings → Secrets → Actions**) to enable signing + notarization —
the workflow gracefully falls back to uploading an unsigned artifact if
any are missing:

- `APPLE_DEV_ID_CERT_P12` — base64-encoded `.p12` (`base64 < cert.p12`)
- `APPLE_DEV_ID_CERT_PASSWORD` — password used when exporting the p12
- `APPLE_DEV_ID_IDENTITY` — the `"Developer ID Application: ..."` string
- `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_SPECIFIC_PASSWORD` — for
  `notarytool`

## Files

- `build_app.py` — PyInstaller entry point (`make bundle`).
- `tray_app.py` — menu-bar app; spawns uvicorn, waits for `/api/health`.
- `hotkey.py` — global `⌥⌘Space` hook opening the studio URL. Requires
  the user to grant *Input Monitoring* + *Accessibility* on first
  launch.
- `updater.py` — best-effort GitHub Releases check; surfaces newer
  versions but never auto-installs.
- `requirements.txt` — `pyinstaller`, `rumps`, `pynput`.
