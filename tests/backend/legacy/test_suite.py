"""
Automated Verification Suite for Local LLM Studio Tier 2 Upgrades.
Tests security sandbox, context compaction, model capabilities, artifacts, and backup/restore.
"""

import os
import sys

import pytest

# Ensure parent directory is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import artifacts, backup, context_manager, model_capabilities, security


def run_tests():
    print("==================================================")
    print("  Local LLM Studio: Tier 2 Verification Suite     ")
    print("==================================================")

    # 1. Security Tests
    print("\n[1] Security Sandbox Tests:")
    p = security.sanitize_and_resolve_path("README.md")
    assert os.path.exists(p), "Valid path resolution failed"
    print("  [PASS] Path sanitization resolves valid workspace file.")

    traversal_caught = False
    try:
        security.sanitize_and_resolve_path("../../Windows/System32")
    except security.SecurityException:
        traversal_caught = True
    assert traversal_caught, "Path traversal attack was not blocked!"
    print("  [PASS] Path traversal attack strictly blocked.")

    timeout_res = security.run_sandboxed_python("import time; time.sleep(3)", timeout_seconds=1)
    assert timeout_res["status"] == "timeout", "Subprocess timeout failed to trigger"
    print("  [PASS] Subprocess timeout enforced (terminated runaway loop).")

    # 2. Context Manager Tests
    print("\n[2] Context Management & Compaction Tests:")
    dummy_history = [{"role": "user", "content": f"Turn {i}: " + ("data " * 200)} for i in range(45)]
    # Use a small-context model so compaction is guaranteed to trigger.
    compacted = context_manager.prepare_compacted_context(
        model_name="moondream",  # 2048 context window → forces compaction
        system_prompt="Base System",
        project_instructions="Project Scope",
        conversation_history=dummy_history,
        current_user_message="Current task",
        file_attachments_context="Attached code preview",
    )
    tokens = context_manager.estimate_messages_tokens(compacted)
    caps = model_capabilities.get_model_capabilities("moondream")
    budget = int(caps["context_window"] * 0.75)
    assert tokens <= budget, f"Compaction overflowed budget: {tokens} > {budget}"
    assert any("[Context Compaction" in m["content"] for m in compacted), "Summary block missing"
    print(
        f"  [PASS] Context compacted cleanly into {len(compacted)} turns ({tokens} estimated tokens, budget {budget})."
    )

    # 3. Model Capabilities & Vision Tests
    print("\n[3] Model Capabilities & Vision Tests:")
    hermes_caps = model_capabilities.get_model_capabilities("hermes3")
    assert hermes_caps["vision"] is False, "Hermes should be text-only"
    assert hermes_caps["tools"] is True, "Hermes should have tool capability"
    vision_warn = model_capabilities.validate_attachments_for_model(
        "hermes3", [{"filename": "screenshot.png", "mime_type": "image/png"}]
    )
    assert vision_warn is not None, "Vision warning should trigger on text-only model"
    print("  [PASS] Model capability detection & vision safety guards verified.")

    # 4. Artifact System Tests
    print("\n[4] Artifact Generation & Extraction Tests:")
    sample_text = (
        "Here is the generated script:\n"
        '<artifact name="fib.py" type="code" language="python">\n'
        "def fib(n):\n"
        "    return n if n <= 1 else fib(n-1) + fib(n-2)\n"
        "</artifact>\n"
        "You can run it directly."
    )
    created_artifacts = artifacts.extract_and_save_artifacts(sample_text)
    assert len(created_artifacts) == 1, "Failed to extract artifact"
    assert created_artifacts[0]["name"] == "fib.py", "Artifact name mismatch"
    assert created_artifacts[0]["language"] == "python", "Artifact language mismatch"
    print(f"  [PASS] Successfully extracted and saved artifact: {created_artifacts[0]['name']}")

    # 5. Backup & Restore Tests
    print("\n[5] Workspace Backup & Restore Tests:")
    exported = backup.export_full_workspace()
    assert "conversations" in exported and "projects" in exported and "artifacts" in exported
    imported = backup.import_workspace(exported)
    print(f"  [PASS] Full JSON workspace backup & restore verified ({imported}).")

    print("\n==================================================")
    print("  ALL TIER 2 ARCHITECTURE TESTS PASSED (100%)    ")
    print("==================================================")


@pytest.mark.requires_sandbox
def test_all():
    """pytest entry point — runs the whole tier-2 suite as one test."""
    run_tests()


if __name__ == "__main__":
    run_tests()
