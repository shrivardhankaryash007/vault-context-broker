"""Local-only sensitive candidate audit using local Ollama."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.utils import truncate_words

_PROPOSAL_SCHEMA = """
{
  "is_sensitive": bool,
  "reason": "string",
  "confidence": float
}
"""


def sanitize_reason(reason: str, content: str) -> str:
    """Sanitize the proposed reason to ensure it does not leak raw note excerpts.

    Args:
        reason: Model-generated reason string.
        content: Raw note content.

    Returns:
        A short, capped, excerpt-free reason.
    """

    import re

    # 1. Strip newlines and normalize spacing
    reason = " ".join(reason.split())

    # 2. Cap length
    if len(reason) > 100:
        reason = reason[:97] + "..."

    # 3. Detect quotes or direct 3-word shingles from the note content
    clean_content = re.sub(r"[^\w\s]", "", content.lower())
    clean_reason = re.sub(r"[^\w\s]", "", reason.lower())

    reason_words = clean_reason.split()
    overlap_detected = False
    shingle_size = 3
    if len(reason_words) >= shingle_size:
        for i in range(len(reason_words) - shingle_size + 1):
            shingle = " ".join(reason_words[i : i + shingle_size])
            if shingle in clean_content:
                overlap_detected = True
                break

    if overlap_detected or '"' in reason or "'" in reason:
        return "sensitive content category detected (redacted)"

    return reason


def query_ollama_proposal(
    config: VaultConfig,
    file_path: Path,
    content: str,
) -> dict[str, Any] | None:
    """Query local Ollama to propose if a note is sensitive.

    Args:
        config: Runtime configuration.
        file_path: Path to the note.
        content: Raw content of the note.

    Returns:
        A dict with proposal details (is_sensitive, reason, confidence) or None.
    """

    excerpt = truncate_words(content.replace("\n", " "), 600)
    prompt = (
        "Analyze this markdown note. Determine if it contains highly personal, sensitive, "
        "or confidential content (e.g., private self-reflections, chat history with models, "
        "credentials, journals, or emotional logs) that should be restricted from cloud seats.\n"
        "Provide a high-level category or category-style description for the 'reason' (e.g., "
        "'personal journal entry', 'API credential leak', 'emotional reflection', 'chat transcript log').\n"
        "CRITICAL SAFETY RULE: Under no circumstances are you allowed to quote, paraphrase, or include "
        "exact text/words from the note content itself in the 'reason'. The 'reason' must be entirely "
        "generic, category-style, and abstract.\n"
        "Respond ONLY with a JSON object. No explanation, no conversational filler, "
        "no markdown tags around JSON.\n"
        f"JSON Schema:\n{_PROPOSAL_SCHEMA}\n\n"
        f"File Name: {file_path.name}\n\n"
        f"Note Content:\n{excerpt}"
    )

    payload = json.dumps(
        {
            "model": config.summarizer.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 256, "temperature": 0.1},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"{config.summarizer.ollama_base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        timeout = getattr(config.summarizer, "timeout_seconds", 30)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None

    text = raw.get("response")
    if not text:
        return None

    try:
        extracted = json.loads(str(text))
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(extracted, dict):
        return None

    raw_reason = str(extracted.get("reason", "No reason provided."))
    sanitized_reason = sanitize_reason(raw_reason, content)

    return {
        "is_sensitive": bool(extracted.get("is_sensitive", False)),
        "reason": sanitized_reason,
        "confidence": float(extracted.get("confidence", 0.0)),
    }
