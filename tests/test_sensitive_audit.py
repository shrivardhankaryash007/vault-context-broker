"""Tests for local-only Ollama sensitive proposal logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from vault_context_mcp.config import SummarizerConfig, VaultConfig
from vault_context_mcp.sensitive_audit import query_ollama_proposal, sanitize_reason


def test_query_ollama_proposal_sensitive() -> None:
    config = VaultConfig(
        vault_root="/tmp/vault",
        index_path="/tmp/idx",
        sensitivity_map_path="/tmp/map",
        summarizer=SummarizerConfig(
            provider="ollama",
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3.1:8b",
            timeout_seconds=5,
        ),
    )

    file_path = Path("/tmp/vault/note.md")
    content = "Some sensitive journal text..."

    # Mock response object
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {
            "response": json.dumps(
                {
                    "is_sensitive": True,
                    "reason": "Contains personal journal reflection",
                    "confidence": 0.9,
                }
            )
        }
    ).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        proposal = query_ollama_proposal(config, file_path, content)

        assert proposal is not None
        assert proposal["is_sensitive"] is True
        assert proposal["reason"] == "Contains personal journal reflection"
        assert proposal["confidence"] == 0.9


def test_query_ollama_proposal_not_sensitive() -> None:
    config = VaultConfig(
        vault_root="/tmp/vault",
        index_path="/tmp/idx",
        sensitivity_map_path="/tmp/map",
        summarizer=SummarizerConfig(
            provider="ollama",
            ollama_base_url="http://localhost:11434",
            ollama_model="llama3.1:8b",
            timeout_seconds=5,
        ),
    )

    file_path = Path("/tmp/vault/note.md")
    content = "Some generic documentation..."

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {
            "response": json.dumps(
                {
                    "is_sensitive": False,
                    "reason": "Documentation on gears.",
                    "confidence": 0.1,
                }
            )
        }
    ).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        proposal = query_ollama_proposal(config, file_path, content)

        assert proposal is not None
        assert proposal["is_sensitive"] is False
        assert proposal["reason"] == "Documentation on gears."
        assert proposal["confidence"] == 0.1


def test_query_ollama_proposal_error_handling() -> None:
    config = VaultConfig(
        vault_root="/tmp/vault",
        index_path="/tmp/idx",
        sensitivity_map_path="/tmp/map",
    )

    file_path = Path("/tmp/vault/note.md")
    content = "Irrelevant content"

    # Simulate timeout or connection failure
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        proposal = query_ollama_proposal(config, file_path, content)
        assert proposal is None


def test_sanitize_reason_removes_newlines_and_spaces() -> None:
    reason = "  Personal\n  journal  reflection  "
    content = "Some note content."
    assert sanitize_reason(reason, content) == "Personal journal reflection"


def test_sanitize_reason_caps_length() -> None:
    reason = "A" * 150
    content = "Some note content."
    sanitized = sanitize_reason(reason, content)
    assert len(sanitized) == 100
    assert sanitized.endswith("...")


def test_sanitize_reason_redacts_direct_excerpt_overlap() -> None:
    content = "Alex requested a new gearbox widget assembly build."
    # Overlapping 3-word phrase "gearbox widget assembly" should trigger redaction
    reason = "Mentions the gearbox widget assembly model."
    assert sanitize_reason(reason, content) == "sensitive content category detected (redacted)"


def test_sanitize_reason_redacts_quotes() -> None:
    content = "Secrets inside."
    reason = 'This note contains "secrets" information.'
    assert sanitize_reason(reason, content) == "sensitive content category detected (redacted)"
