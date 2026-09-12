"""Hotkey helper tests. Doesn't actually install a global hook — that
requires macOS + accessibility grant. We test the pure `open_studio`
routing and the error-path branch when pynput is absent."""

from __future__ import annotations

import sys
from unittest.mock import patch

from desktop import hotkey


class TestOpenStudio:
    def test_opens_the_configured_url(self) -> None:
        with patch("desktop.hotkey.webbrowser.open") as mock_open:
            hotkey.open_studio("http://127.0.0.1:8080")
        mock_open.assert_called_once_with("http://127.0.0.1:8080")


class TestRegisterHotkey:
    def test_returns_none_and_reports_error_when_pynput_missing(self, monkeypatch) -> None:
        # Force the pynput import inside register_hotkey to fail.
        monkeypatch.setitem(sys.modules, "pynput", None)
        errors: list[Exception] = []
        t = hotkey.register_hotkey("http://127.0.0.1:8080", on_error=errors.append)
        assert t is None
        assert len(errors) == 1
        assert isinstance(errors[0], ImportError)
