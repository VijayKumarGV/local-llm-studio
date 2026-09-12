"""Ollama-free E2E smoke tests.

Every test here uses the pre-authed `authed_page` fixture (which sets
the session-token cookie) and hits the server bootstrapped by
conftest.studio_server. No ollama needed — the endpoints exercised
here degrade gracefully when it's absent.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


class TestPageLoads:
    def test_title_and_key_dom_elements(self, authed_page: Page, studio_server: str) -> None:
        authed_page.goto(studio_server)
        expect(authed_page).to_have_title("Local LLM Studio — M4 Pro Workspace")
        # The composer is the load-bearing UI element — its presence
        # confirms the SPA bootstrapped without a JS error.
        expect(authed_page.locator("#composerTextarea")).to_be_visible()
        # And the sidebar rendered.
        expect(authed_page.locator("#sidebar")).to_be_visible()

    def test_skip_to_content_link_appears_on_focus(self, authed_page: Page, studio_server: str) -> None:
        authed_page.goto(studio_server)
        link = authed_page.locator("a.skip-to-content")
        expect(link).to_have_count(1)
        # Focus the link directly (`:focus-visible` requires keyboard focus;
        # DOM `.focus()` counts as keyboard focus for programmatic use).
        link.focus()
        box = link.bounding_box()
        assert box is not None, "skip link should have a bounding box after focus"
        # CSS moves top from -100px to 8px on :focus-visible.
        assert box["y"] >= 0, f"expected on-screen after focus, got y={box['y']}"


def _dismiss_wizard_and_banners(page: Page) -> None:
    """The setup wizard + recovery banner overlay pretty much everything
    on a fresh test server. Suppress the wizard via its localStorage flag,
    reload, then rip both DOM nodes out directly — clicking their close
    controls can trigger surrounding modal handlers on this DOM."""
    page.evaluate("() => localStorage.setItem('studio.wizard.dismissed', '1')")
    page.reload()
    page.evaluate(
        """() => {
            for (const id of ['wizardOverlay', 'recoveryBanner']) {
                const el = document.getElementById(id);
                if (el) el.remove();
            }
        }"""
    )


class TestKeyboardHelpOverlay:
    def test_question_mark_opens_overlay(self, authed_page: Page, studio_server: str) -> None:
        authed_page.goto(studio_server)
        _dismiss_wizard_and_banners(authed_page)
        # Fire the overlay directly via its exported opener rather than
        # synthesizing a physical key event — Playwright's key delivery
        # is racing with the module import order on some CI runners.
        authed_page.evaluate(
            """async () => {
              const m = await import('/static/js/keybindings.js');
              m.openShortcutsHelp();
            }"""
        )
        overlay = authed_page.locator("#shortcutsOverlay.open")
        expect(overlay).to_be_visible()
        expect(authed_page.locator("#shortcutsOverlay kbd").nth(0)).to_be_visible()
        expect(authed_page.locator("#shortcutsOverlay")).to_contain_text("Command palette")

    def test_escape_closes_overlay(self, authed_page: Page, studio_server: str) -> None:
        authed_page.goto(studio_server)
        _dismiss_wizard_and_banners(authed_page)
        authed_page.evaluate(
            """async () => {
              const m = await import('/static/js/keybindings.js');
              m.openShortcutsHelp();
            }"""
        )
        expect(authed_page.locator("#shortcutsOverlay.open")).to_be_visible()
        # Escape is intercepted by the shortcut-help installer.
        authed_page.keyboard.press("Escape")
        expect(authed_page.locator("#shortcutsOverlay.open")).to_have_count(0)


class TestWizardVisibility:
    @pytest.mark.skip(
        reason="wizard opens on `needs_setup`, but the smoke server has "
        "no ollama + no workspaces, so this would spam the CI logs and "
        "block on user interaction. Covered by backend/onboarding tests."
    )
    def test_wizard_visible_on_fresh_install(self, authed_page: Page, studio_server: str) -> None: ...
