"""
Global hotkey (⌥⌘Space) → open the Studio URL in the browser.

macOS requires the user to grant *Input Monitoring* + *Accessibility*
permission to the .app bundle before pynput can register the hook.
Both are one-off Settings → Privacy panels; we surface a hint via
the tray if the hotkey fails to register.

pynput is imported lazily so this module can be imported (and unit-
tested for the pure `on_activate` helper) without the native bridge.
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable

DEFAULT_HOTKEY = "<alt>+<cmd>+<space>"
log = logging.getLogger("studio.hotkey")


def open_studio(url: str) -> None:
    """Callback invoked when the hotkey fires. Extracted so tests can call
    it directly without pynput."""
    webbrowser.open(url)


def register_hotkey(
    url: str,
    combo: str = DEFAULT_HOTKEY,
    on_error: Callable[[Exception], None] | None = None,
) -> threading.Thread | None:
    """Register `combo` and route it to `open_studio(url)`. Runs the pynput
    listener in a daemon thread and returns it. Returns None if pynput is
    unavailable or the hook can't be installed (permission not granted)."""
    try:
        from pynput import keyboard
    except ImportError as e:
        log.warning("pynput not installed; global hotkey disabled (%s)", e)
        if on_error:
            on_error(e)
        return None

    def _fire() -> None:
        try:
            open_studio(url)
        except Exception:
            log.exception("hotkey handler failed")

    def _runner() -> None:
        try:
            with keyboard.GlobalHotKeys({combo: _fire}) as h:
                h.join()
        except Exception as e:
            log.warning("failed to install global hotkey %s: %s", combo, e)
            if on_error:
                on_error(e)

    t = threading.Thread(target=_runner, name="studio-hotkey", daemon=True)
    t.start()
    return t
