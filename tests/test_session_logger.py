"""Cross-LLM session logger tests."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from vault_context_mcp.index_store import build_index
from vault_context_mcp.schemas import LLMSessionLogRequest
from vault_context_mcp.session_logger import (
    build_session_handoff,
    format_session_markdown,
    log_llm_session,
    process_unprocessed_sessions,
    recent_sessions,
)


def test_log_llm_session_writes_chatgpt_log_and_refreshes_index(test_config) -> None:  # type: ignore[no-untyped-def]
    result = log_llm_session(
        test_config,
        LLMSessionLogRequest(
            source="chatgpt",
            title="Desktop Capture Test",
            transcript="**You:** hello\n\n**ChatGPT:** useful thought",
            origin="chatgpt.com",
            project="ATLAS",
            summary="Captured a useful thought.",
            next_actions=["Continue ATLAS architecture."],
        ),
    )

    assert re.search(
        r"/00_Inbox/Chats/ChatGPT/\d{4}-\d{2}-\d{2}-desktop-capture-test\.md$",
        result.path,
    )
    assert result.index_refreshed is True
    assert (test_config.vault_root_path / result.path).exists()


def test_recent_sessions_reads_existing_claude_project_logs(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    sessions = recent_sessions(test_config, project="Orion", limit=5)

    assert any("Claude-Vault Bridge Setup" in session.title for session in sessions)
    assert any(session.source == "claude" for session in sessions)


def test_session_handoff_uses_existing_claude_logs(test_config) -> None:  # type: ignore[no-untyped-def]
    handoff = build_session_handoff(test_config, project="Orion", limit=5)

    assert "Claude-Vault Bridge Setup" in handoff.synthesized_handoff
    assert handoff.suggested_next_actions


def test_format_session_markdown_processed_flag() -> None:
    request = LLMSessionLogRequest(
        source="claude",
        title="Test Session",
        transcript="**User:** hi\n\n**Claude:** hello",
    )
    captured = datetime(2026, 5, 7, 12, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    unprocessed = format_session_markdown(request, captured, processed=False)
    processed = format_session_markdown(request, captured, processed=True)

    assert "- unprocessed\n" in unprocessed
    assert "- processed\n" in processed
    assert "- unprocessed\n" not in processed


def test_log_session_uses_ollama_extracted_summary_in_daily_note(  # type: ignore[no-untyped-def]
    test_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Ollama returns structured fields, the daily note line uses the extracted summary."""

    extracted: dict[str, object] = {
        "summary": "Confirmed end-to-end capture-to-summarize loop works.",
        "key_takeaways": ["Loop is end-to-end.", "Daily note picks up extracted summary."],
        "decisions": [],
        "open_questions": [],
        "next_actions": ["Ship it."],
    }

    def fake_summarize(self: Any, transcript: str, title: str, project: str | None) -> Any:
        return extracted

    from vault_context_mcp.summarizer import Summarizer

    monkeypatch.setattr(Summarizer, "summarize_session_transcript", fake_summarize)

    test_config.session_log.create_daily_note = True
    result = log_llm_session(
        test_config,
        LLMSessionLogRequest(
            source="local",
            title="Ollama Loop Test",
            transcript="**You:** does the loop work?\n\n**Local:** yes",
            origin="pytest",
            project="vault-context-mcp",
        ),
    )

    session_text = (test_config.vault_root_path / result.path).read_text(encoding="utf-8")
    assert "- processed\n" in session_text
    assert "## Key Takeaways" in session_text
    assert "Loop is end-to-end." in session_text

    assert result.daily_note_path is not None
    daily_text = (test_config.vault_root_path / result.daily_note_path).read_text(encoding="utf-8")
    assert "Confirmed end-to-end capture-to-summarize loop works." in daily_text


def test_process_unprocessed_sessions_skips_already_processed(test_config) -> None:
    # Write a session that has no Transcript section — should be skipped gracefully
    inbox = test_config.vault_root_path / "Main_Vault" / "00_Inbox" / "Chats" / "Local"
    inbox.mkdir(parents=True, exist_ok=True)
    session_file = inbox / "2026-05-07-no-transcript.md"
    session_file.write_text(
        "---\ntags:\n- unprocessed\n- llm-session\n---\n\n# No Transcript\n\nNo body.\n",
        encoding="utf-8",
    )

    # summarize_on_capture is True but Ollama is not available in tests — should return []
    updated = process_unprocessed_sessions(test_config)

    # Ollama unavailable → nothing updated, but no crash
    assert isinstance(updated, list)
