"""Model capability lookup + vision validation."""

from __future__ import annotations

from backend import model_capabilities as mc


class TestGetModelCapabilities:
    def test_exact_match(self) -> None:
        caps = mc.get_model_capabilities("qwen2.5:32b")
        assert caps["tools"] is True
        assert caps["context_window"] == 32768
        assert caps["model_name"] == "qwen2.5:32b"

    def test_prefix_match_longest_wins(self) -> None:
        # `qwen2.5-coder` should win over `qwen2.5` because it's longer/more specific
        caps = mc.get_model_capabilities("qwen2.5-coder:custom-tag")
        assert caps["coding"] == "elite"

    def test_case_insensitive(self) -> None:
        caps = mc.get_model_capabilities("QWEN2.5:32B")
        assert caps["tools"] is True

    def test_unknown_model_heuristic_defaults(self) -> None:
        # Model not in the registry — heuristic infers from name
        caps = mc.get_model_capabilities("some-random-model:1b")
        assert "context_window" in caps
        assert "vision" in caps
        assert "tools" in caps

    def test_unknown_vision_by_name(self) -> None:
        # Heuristic should mark obvious vision model names
        caps = mc.get_model_capabilities("some-vl-model:latest")
        assert caps["vision"] is True

    def test_unknown_reasoning_by_name(self) -> None:
        caps = mc.get_model_capabilities("myorg-r1-distill:7b")
        assert caps["thinking"] is True
        # Thinking models generally don't advertise tool calling
        assert caps["tools"] is False

    def test_size_heuristic_for_context_window(self) -> None:
        big = mc.get_model_capabilities("mystery-70b")
        small = mc.get_model_capabilities("mystery-tiny")
        assert big["context_window"] > small["context_window"]


class TestValidateAttachmentsForModel:
    def test_no_attachments_returns_none(self) -> None:
        assert mc.validate_attachments_for_model("qwen2.5:32b", None) is None
        assert mc.validate_attachments_for_model("qwen2.5:32b", []) is None

    def test_image_on_text_only_model_warns(self) -> None:
        warning = mc.validate_attachments_for_model(
            "qwen2.5:32b",  # text-only
            [{"filename": "screenshot.png", "mime_type": "image/png"}],
        )
        assert warning is not None
        assert "vision" in warning.lower()

    def test_image_on_vision_model_ok(self) -> None:
        warning = mc.validate_attachments_for_model(
            "minicpm-v",
            [{"filename": "screenshot.png", "mime_type": "image/png"}],
        )
        assert warning is None

    def test_non_image_attachment_never_warns(self) -> None:
        assert (
            mc.validate_attachments_for_model(
                "qwen2.5:32b",
                [{"filename": "readme.md", "mime_type": "text/markdown"}],
            )
            is None
        )

    def test_detection_by_filename_extension(self) -> None:
        # Missing mime_type — should still detect image via extension
        warning = mc.validate_attachments_for_model(
            "qwen2.5:32b",
            [{"filename": "chart.jpg"}],
        )
        assert warning is not None
