"""Token estimation + context compaction."""

from __future__ import annotations

import pytest

from backend import context_manager as cm


class TestEstimateTokens:
    def test_empty_string_is_zero(self) -> None:
        assert cm.estimate_tokens("") == 0

    def test_none_is_zero(self) -> None:
        assert cm.estimate_tokens(None) == 0  # type: ignore[arg-type]

    def test_short_string_is_positive(self) -> None:
        assert cm.estimate_tokens("hello world") > 0

    def test_longer_string_yields_more_tokens(self) -> None:
        short = cm.estimate_tokens("hi")
        long = cm.estimate_tokens("hi " * 500)
        assert long > short * 100

    def test_at_least_one_token_for_any_nonempty(self) -> None:
        # Even a single character must round up to ≥1 (matches the max(1, …) guard).
        assert cm.estimate_tokens("x") >= 1

    def test_fallback_works_without_tiktoken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cm, "_ENC", None)
        # ~3.8 chars/token: a 100-char string ≈ 26 tokens
        n = cm.estimate_tokens("a" * 100)
        assert 20 <= n <= 40


class TestEstimateMessagesTokens:
    def test_empty_list(self) -> None:
        assert cm.estimate_messages_tokens([]) == 0

    def test_accumulates_over_messages(self) -> None:
        msgs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        total = cm.estimate_messages_tokens(msgs)
        # Two messages, each has content + role overhead
        assert total > 0

    def test_role_overhead_applied(self) -> None:
        # Empty content still costs the +4 role overhead per message
        msgs = [{"role": "user", "content": ""}]
        assert cm.estimate_messages_tokens(msgs) == 4


class TestPrepareCompactedContext:
    def test_short_conversation_fits_without_compaction(self) -> None:
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]
        result = cm.prepare_compacted_context(
            model_name="qwen2.5:32b",  # 32K ctx — everything fits
            system_prompt="You are helpful.",
            project_instructions="",
            conversation_history=history,
            current_user_message="what's up",
            file_attachments_context="",
        )
        assert result[0]["role"] == "system"
        assert result[-1]["role"] == "user"
        assert result[-1]["content"] == "what's up"
        # No compaction summary block for short history
        assert not any("[Context Compaction" in m["content"] for m in result)

    def test_long_conversation_triggers_compaction_on_small_model(self) -> None:
        history = [
            {"role": "user", "content": f"Turn {i}: " + ("data " * 200)}
            for i in range(45)
        ]
        result = cm.prepare_compacted_context(
            model_name="moondream",  # 2048 ctx forces compaction
            system_prompt="Base System",
            project_instructions="Project Scope",
            conversation_history=history,
            current_user_message="Current task",
            file_attachments_context="",
        )
        assert any("[Context Compaction" in m["content"] for m in result)
        # Never exceeds the budget (context_window * 0.75)
        total = cm.estimate_messages_tokens(result)
        assert total <= int(2048 * 0.75)

    def test_project_instructions_prepended_to_system(self) -> None:
        result = cm.prepare_compacted_context(
            model_name="qwen2.5:32b",
            system_prompt="System.",
            project_instructions="Project instructions.",
            conversation_history=[],
            current_user_message="hi",
            file_attachments_context="",
        )
        # First message combines project + system
        assert "Project instructions." in result[0]["content"]
        assert "System." in result[0]["content"]

    def test_attachment_context_appended_to_user_message(self) -> None:
        result = cm.prepare_compacted_context(
            model_name="qwen2.5:32b",
            system_prompt="",
            project_instructions="",
            conversation_history=[],
            current_user_message="analyze this",
            file_attachments_context="[File: x.py]\ncode content",
        )
        assert "code content" in result[-1]["content"]
        assert "analyze this" in result[-1]["content"]

    def test_giant_attachment_truncated(self) -> None:
        giant = "a" * 500_000  # 500 KB of attachment context
        result = cm.prepare_compacted_context(
            model_name="qwen2.5:32b",
            system_prompt="",
            project_instructions="",
            conversation_history=[],
            current_user_message="q",
            file_attachments_context=giant,
        )
        # The user message + truncated attachment should stay under 35% of budget
        assert "[File attachment context truncated" in result[-1]["content"]
