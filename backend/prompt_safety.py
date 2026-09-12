"""Cheap prompt-injection heuristics.

Not a real defense — a truly adversarial input will bypass regex. But
catches the common lazy-copy-paste attacks (`ignore all previous
instructions`, jailbreak/DAN prompts, chat-template injection, etc.)
and gives the frontend a warning it can surface to the user.

Behavior:
  - `scan(text)` always runs on user messages; returns a list of findings
  - Orchestrator emits `event: prompt_warning` when findings > 0
  - When `block_prompt_injection` setting is on, the turn is refused
    with a 400-ish SSE error and no LLM call is made.
"""

from __future__ import annotations

import re
from typing import TypedDict

_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"ignore\s+(all\s+|the\s+|any\s+)*(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|context)",
            re.I,
        ),
        "instruction_override",
        "Attempts to override earlier instructions.",
    ),
    (
        re.compile(r"you\s+are\s+now\s+(dan|jailbroken|unrestricted)|jailbreak|roleplay\s+as", re.I),
        "persona_override",
        "Persona / jailbreak framing detected.",
    ),
    (
        re.compile(r"(reveal|print|show|repeat|leak|dump)\s+(your\s+|the\s+)?(system\s+prompt|instructions)", re.I),
        "prompt_exfiltration",
        "Request to reveal the system prompt.",
    ),
    (
        re.compile(r"<\|(im_end|im_start|system|user|assistant|endoftext)\|>", re.I),
        "chat_template_injection",
        "Chat-template control tokens in user input.",
    ),
    (
        re.compile(r"repeat\s+(the\s+)?(word|phrase|token)[s]?\s+.{1,40}\s+(forever|infinitely|for\s+ever)", re.I),
        "resource_exhaustion",
        "Requests unbounded repetition (resource attack).",
    ),
    (
        re.compile(r"disregard\s+(all\s+)?(safety|content|policy)", re.I),
        "safety_bypass",
        "Explicit safety-bypass request.",
    ),
]


class Finding(TypedDict):
    kind: str
    match: str
    description: str


def scan(text: str) -> list[Finding]:
    """Return matched heuristics. Empty list = clean."""
    if not text:
        return []
    findings: list[Finding] = []
    for pattern, kind, description in _PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append(
                {
                    "kind": kind,
                    "match": m.group(0)[:120],
                    "description": description,
                }
            )
    return findings
