"""
Model Capabilities & Vision Registry for Local LLM Studio.
Dynamically resolves context windows, vision support, and tool calling compatibility.
Optimized for Apple M4 Pro (37 GB unified memory) — can run 32B models comfortably.
"""

from typing import Dict, Any, List, Optional


# Known capability profiles for popular local open-source models
# M4 Pro (37GB) comfortable range: up to ~32B at Q4_K_M (~20GB), or ~70B at Q3_K_M (~28GB)
CAPABILITY_REGISTRY = {
    # === Primary: Uncensored 32B-class (M4 Pro sweet spot) ===
    "qwen2.5:32b": {
        "context_window": 32768,
        "vision": False,
        "tools": True,
        "coding": "elite",
        "thinking": False,
        "description": "Qwen 2.5 32B — Best all-around. 32K context, elite coding, strong reasoning. ~20GB on M4."
    },
    "qwen2.5-coder:32b": {
        "context_window": 32768,
        "vision": False,
        "tools": True,
        "coding": "elite",
        "thinking": False,
        "description": "Qwen 2.5 Coder 32B — Top-tier code generation, refactoring & debugging. ~20GB on M4."
    },
    "deepseek-r1:32b": {
        "context_window": 65536,
        "vision": False,
        "tools": False,
        "coding": "high",
        "thinking": True,
        "description": "DeepSeek R1 32B — Visible chain-of-thought reasoning. Math, logic, planning. ~20GB on M4."
    },
    "gemma2:27b": {
        "context_window": 8192,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Gemma 2 27B — Google's powerful open model. Strong instruction following. ~16GB on M4."
    },
    "mistral-small3.1": {
        "context_window": 32768,
        "vision": True,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Mistral Small 3.1 24B — Vision + tools, excellent instruction following. ~14GB on M4."
    },
    "phi4": {
        "context_window": 16384,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Microsoft Phi-4 14B — Surprisingly capable small model. Great for reasoning. ~9GB on M4."
    },
    # === Uncensored models ===
    "hermes3": {
        "context_window": 131072,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Nous Hermes 3 — Completely uncensored, expert tool use. 8B (~5GB) or 70B (~43GB) on M4."
    },
    "dolphin3.0-llama3.1": {
        "context_window": 131072,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Dolphin 3.0 Llama 3.1 — Fully uncensored, no guardrails, trained by Eric Hartford."
    },
    "dolphin-llama3": {
        "context_window": 8192,
        "vision": False,
        "tools": True,
        "coding": "moderate",
        "thinking": False,
        "description": "Dolphin Llama 3 — Completely unrestricted conversational model."
    },
    "dolphin-mistral": {
        "context_window": 32768,
        "vision": False,
        "tools": True,
        "coding": "moderate",
        "thinking": False,
        "description": "Dolphin Mistral — Unrestricted Mistral variant. Fast and capable."
    },
    # === Large context / flagship ===
    "llama3.1:70b": {
        "context_window": 131072,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Llama 3.1 70B — Meta's flagship. 128K context. Fits at Q3_K_M (~28GB) on M4."
    },
    "llama3.3:70b": {
        "context_window": 131072,
        "vision": False,
        "tools": True,
        "coding": "high",
        "thinking": False,
        "description": "Llama 3.3 70B — Meta's latest 70B. Fits at Q3_K_M (~28GB) on M4."
    },
    # === Thinking / reasoning ===
    "qwq": {
        "context_window": 32768,
        "vision": False,
        "tools": False,
        "coding": "high",
        "thinking": True,
        "description": "QwQ 32B — Qwen's reasoning model. Extended chain-of-thought for complex problems."
    },
    "deepseek-r1": {
        "context_window": 65536,
        "vision": False,
        "tools": False,
        "coding": "high",
        "thinking": True,
        "description": "DeepSeek R1 8B — Visible chain-of-thought. Distilled reasoning model."
    },
    # === Vision models ===
    "llava": {
        "context_window": 4096,
        "vision": True,
        "tools": False,
        "coding": "moderate",
        "thinking": False,
        "description": "LLaVA — Multimodal vision model for image understanding."
    },
    "minicpm-v": {
        "context_window": 8192,
        "vision": True,
        "tools": False,
        "coding": "moderate",
        "thinking": False,
        "description": "MiniCPM-V — Efficient multimodal vision model, strong OCR and chart reading."
    },
    "moondream": {
        "context_window": 2048,
        "vision": True,
        "tools": False,
        "coding": "basic",
        "thinking": False,
        "description": "Moondream 2 — Ultra-compact, fast multimodal vision model."
    },
    # === Coding specialists ===
    "qwen2.5-coder": {
        "context_window": 32768,
        "vision": False,
        "tools": True,
        "coding": "elite",
        "thinking": False,
        "description": "Qwen 2.5 Coder — State-of-the-art code generation, debugging & refactoring."
    },
    "codellama": {
        "context_window": 100000,
        "vision": False,
        "tools": False,
        "coding": "elite",
        "thinking": False,
        "description": "Code Llama — Meta's dedicated coding model."
    },
}


def get_model_capabilities(model_name: str) -> Dict[str, Any]:
    """Inspect model name and return its capabilities."""
    clean_name = model_name.lower().strip()

    # Exact match first (e.g. "qwen2.5:32b")
    if clean_name in CAPABILITY_REGISTRY:
        profile = CAPABILITY_REGISTRY[clean_name].copy()
        profile["model_name"] = model_name
        return profile

    # Prefix/substring match (longest key wins)
    best_key = None
    best_len = 0
    for k in CAPABILITY_REGISTRY:
        if k in clean_name and len(k) > best_len:
            best_key = k
            best_len = len(k)

    if best_key:
        profile = CAPABILITY_REGISTRY[best_key].copy()
        profile["model_name"] = model_name
        return profile

    # Heuristic detection for unknown or custom models
    is_vision = any(term in clean_name for term in ["vision", "vl", "llava", "moondream", "clip", "minicpm-v"])
    is_coder = "coder" in clean_name or "code" in clean_name
    is_thinking = any(term in clean_name for term in ["r1", "qwq", "think", "reason"])

    # Infer context from size hint in name
    ctx = 131072 if "70b" in clean_name else (32768 if "32b" in clean_name or "27b" in clean_name else 8192)

    return {
        "model_name": model_name,
        "context_window": ctx,
        "vision": is_vision,
        "tools": not is_thinking,
        "coding": "high" if is_coder else "moderate",
        "thinking": is_thinking,
        "description": f"Local model: {model_name}"
    }


def validate_attachments_for_model(model_name: str, attachments: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """
    Check if attachments contain images while the model is text-only.
    Returns warning/error string if incompatible, or None if valid.
    """
    if not attachments:
        return None

    caps = get_model_capabilities(model_name)
    has_image = any(
        att.get("mime_type", "").startswith("image/") or
        att.get("filename", "").lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
        for att in attachments
    )

    if has_image and not caps.get("vision", False):
        return (
            f"The selected model '{model_name}' is a text-only language model and does not support image vision. "
            f"To analyze images, install and switch to a vision model (e.g. 'ollama pull llava' or 'ollama pull moondream')."
        )

    return None
