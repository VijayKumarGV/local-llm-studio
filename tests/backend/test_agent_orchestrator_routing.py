"""Model router + attachment helpers — pure functions in the orchestrator."""

from __future__ import annotations

from backend.agent_orchestrator import _has_image_attachment, route_model

INSTALLED_FULL = [
    "qwen2.5:32b",
    "qwen2.5-coder:32b",
    "dolphin3:latest",
    "deepseek-r1:14b",
    "llama3.2:1b",
    "minicpm-v:latest",
    "nomic-embed-text:latest",
]


class TestHasImageAttachment:
    def test_none_or_empty(self) -> None:
        assert _has_image_attachment(None) is False
        assert _has_image_attachment([]) is False

    def test_by_mime_type(self) -> None:
        assert _has_image_attachment([{"mime_type": "image/png"}]) is True
        assert _has_image_attachment([{"mime_type": "text/plain"}]) is False

    def test_by_extension(self) -> None:
        assert _has_image_attachment([{"filename": "shot.PNG"}]) is True
        assert _has_image_attachment([{"filename": "shot.jpeg"}]) is True
        assert _has_image_attachment([{"filename": "shot.webp"}]) is True
        assert _has_image_attachment([{"filename": "doc.pdf"}]) is False

    def test_mixed_list_returns_true_if_any_image(self) -> None:
        assert _has_image_attachment([
            {"filename": "readme.md"},
            {"filename": "chart.png"},
        ]) is True


class TestRouteModel:
    def test_disabled_returns_requested_unchanged(self) -> None:
        settings = {"auto_route_model": "false"}
        chosen, reason = route_model(
            "qwen2.5:32b", "why does TLS work", None, settings, INSTALLED_FULL,
        )
        assert chosen == "qwen2.5:32b"
        assert "disabled" in reason

    def test_reasoning_keyword_routes_to_reasoning_model(self) -> None:
        chosen, reason = route_model(
            "qwen2.5:32b",
            "Why does TLS 1.3 use ephemeral keys?",
            None,
            {},
            INSTALLED_FULL,
        )
        assert chosen == "deepseek-r1:14b"
        assert "reasoning" in reason

    def test_code_keyword_routes_to_coder(self) -> None:
        chosen, _ = route_model(
            "qwen2.5:32b",
            "Write a Python function to sort a list",
            None,
            {},
            INSTALLED_FULL,
        )
        assert chosen == "qwen2.5-coder:32b"

    def test_trivial_question_routes_to_tiny_model(self) -> None:
        chosen, _ = route_model(
            "qwen2.5:32b", "hi", None, {}, INSTALLED_FULL,
        )
        assert chosen == "llama3.2:1b"

    def test_short_but_code_keeps_coder(self) -> None:
        # `def foo():` is short but has code hint → coder wins over trivial
        chosen, _ = route_model(
            "qwen2.5:32b", "def foo():", None, {}, INSTALLED_FULL,
        )
        assert chosen == "qwen2.5-coder:32b"

    def test_image_forces_vision_model(self) -> None:
        chosen, reason = route_model(
            "qwen2.5:32b",
            "what is in this image",
            None,
            {},
            INSTALLED_FULL,
            attachments=[{"mime_type": "image/png", "filename": "s.png", "id": "x"}],
        )
        assert chosen == "minicpm-v:latest"
        assert "image attachment" in reason

    def test_image_with_vision_capable_requested_model_keeps_it(self) -> None:
        # If user already asked for a vision model, don't second-guess them
        chosen, _ = route_model(
            "minicpm-v:latest",
            "what is this",
            None,
            {},
            INSTALLED_FULL,
            attachments=[{"mime_type": "image/png"}],
        )
        # Vision requested → doesn't re-route
        assert chosen == "minicpm-v:latest"

    def test_workspace_default_override_wins(self) -> None:
        settings = {"project_p123_default_model": "dolphin3:latest"}
        chosen, reason = route_model(
            "qwen2.5:32b",
            "Why does X happen?",  # would normally route to reasoning
            "p123",
            settings,
            INSTALLED_FULL,
        )
        assert chosen == "dolphin3:latest"
        assert "workspace default" in reason

    def test_workspace_default_ignored_if_model_not_installed(self) -> None:
        settings = {"project_p123_default_model": "nonexistent-model:99b"}
        chosen, _ = route_model(
            "qwen2.5:32b",
            "Why does X happen?",
            "p123",
            settings,
            INSTALLED_FULL,
        )
        # Fallback: reasoning heuristic kicks in
        assert chosen == "deepseek-r1:14b"

    def test_falls_back_to_requested_when_nothing_matches(self) -> None:
        chosen, reason = route_model(
            "qwen2.5:32b",
            "just a normal medium-length message with no special keywords in it",
            None,
            {},
            INSTALLED_FULL,
        )
        assert chosen == "qwen2.5:32b"
        assert reason == "default"

    def test_installed_missing_reasoning_model_falls_back(self) -> None:
        installed = ["qwen2.5:32b", "llama3.2:1b"]  # no deepseek-r1 or qwq
        chosen, _ = route_model(
            "qwen2.5:32b",
            "Why does TLS work?",
            None,
            {},
            installed,
        )
        assert chosen == "qwen2.5:32b"  # no reasoning model available → keep requested
