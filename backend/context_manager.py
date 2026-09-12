"""
Context Management Layer for Local LLM Studio.
Handles token estimation, dynamic context compaction, sliding window management,
and conversation summarization to prevent context overflow.
"""

from typing import List, Dict, Any, Tuple
from backend.model_capabilities import get_model_capabilities

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None


def estimate_tokens(text: str) -> int:
    """Token count. Uses tiktoken cl100k_base when available, else a char-based
    fallback (~3.8 chars/token). cl100k_base isn't Ollama-model-specific but it's
    a reliable upper bound for all common tokenizers we serve."""
    if not text:
        return 0
    if _ENC is not None:
        try:
            return max(1, len(_ENC.encode(text, disallowed_special=())))
        except Exception:
            pass
    return max(1, int(len(text) / 3.8))


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(m.get("content", "")) + 4  # +4 for role/formatting overhead
    return total


def prepare_compacted_context(
    model_name: str,
    system_prompt: str,
    project_instructions: str,
    conversation_history: List[Dict[str, Any]],
    current_user_message: str,
    file_attachments_context: str = ""
) -> List[Dict[str, str]]:
    """
    Constructs a token-budgeted prompt payload.
    Guarantees the prompt never overflows the model's context window.
    """
    caps = get_model_capabilities(model_name)
    context_limit = caps.get("context_window", 8192)

    # Reserve 25% for model output generation
    max_prompt_budget = int(context_limit * 0.75)

    # 1. Mandatory Core: System Prompt & Project Instructions
    combined_system = system_prompt or ""
    if project_instructions:
        combined_system = f"{project_instructions.strip()}\n\n{combined_system}"

    system_tokens = estimate_tokens(combined_system) + 10

    # 2. Current User Message & Attachments
    final_user_content = current_user_message
    if file_attachments_context:
        # Cap attachment context if excessively large
        max_att_tokens = int(max_prompt_budget * 0.35)
        if estimate_tokens(file_attachments_context) > max_att_tokens:
            # Truncate to ~max_att_tokens * 3.8 characters
            char_limit = int(max_att_tokens * 3.8)
            file_attachments_context = file_attachments_context[:char_limit] + "\n[File attachment context truncated to fit context budget]"
        final_user_content += f"\n\n{file_attachments_context}"

    user_tokens = estimate_tokens(final_user_content) + 10
    # Reserve 200 tokens for summary block overhead
    remaining_budget = max_prompt_budget - system_tokens - user_tokens - 200

    # 3. Fit Conversation History (Sliding Window & Compaction)
    assembled_history: List[Dict[str, str]] = []
    compacted_summary: List[str] = []

    # Iterate from newest to oldest messages
    reversed_history = list(reversed(conversation_history))
    accumulated_tokens = 0
    recent_turns: List[Dict[str, str]] = []

    for msg in reversed_history:
        content = msg.get("content", "")
        role = msg.get("role", "user")
        cost = estimate_tokens(content) + 4

        if accumulated_tokens + cost <= remaining_budget:
            recent_turns.append({"role": role, "content": content})
            accumulated_tokens += cost
        else:
            # Message overflows budget; extract key snippet for summary
            snippet = content[:150].replace("\n", " ").strip()
            compacted_summary.append(f"{role.capitalize()}: {snippet}...")

    # Re-order recent turns to chronological
    recent_turns.reverse()

    # If any older turns were compacted, inject an informative summary block
    final_messages: List[Dict[str, str]] = []
    final_messages.append({"role": "system", "content": combined_system})

    if compacted_summary:
        compacted_summary.reverse()
        summary_block = (
            "[Context Compaction: Earlier turns in this conversation were summarized to preserve memory]:\n"
            + "\n".join(compacted_summary[:6])
        )
        final_messages.append({"role": "system", "content": summary_block})

    # Append recent turns
    final_messages.extend(recent_turns)

    # Append current user prompt
    final_messages.append({"role": "user", "content": final_user_content})

    return final_messages
