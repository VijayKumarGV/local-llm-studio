"""Prompt loader tests."""

from __future__ import annotations

import pytest

from backend import prompts


class TestLoad:
    def test_returns_stripped_contents(self) -> None:
        got = prompts.load("system_default")
        assert got.startswith("You are an advanced")
        assert not got.endswith("\n"), "load() should strip trailing whitespace"

    def test_missing_prompt_raises_typed_error(self) -> None:
        with pytest.raises(prompts.PromptNotFoundError):
            prompts.load("this-does-not-exist")

    def test_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Cache a real load, then swap the file under it — cached call should
        # return the ORIGINAL contents until reload() is called.
        _ = prompts.load("system_default")
        real_path = prompts.PROMPT_DIR / "system_default.md"
        original = real_path.read_text()
        try:
            real_path.write_text("REPLACED CONTENTS\n", encoding="utf-8")
            assert prompts.load("system_default") != "REPLACED CONTENTS"
            prompts.reload()
            assert prompts.load("system_default") == "REPLACED CONTENTS"
        finally:
            real_path.write_text(original, encoding="utf-8")
            prompts.reload()


class TestAllRealPromptsPresent:
    """Every prompt file the codebase loads is checked-in and non-empty."""

    @pytest.mark.parametrize(
        "name",
        ["system_default", "hardware_context", "tool_hint", "critique", "hyde", "rerank"],
    )
    def test_loadable_and_nonempty(self, name: str) -> None:
        text = prompts.load(name)
        assert text.strip(), f"prompt {name!r} is empty"
